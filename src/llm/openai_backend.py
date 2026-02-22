"""Generic OpenAI-compatible API backend.

Works with any OpenAI-compatible API including:
- OpenAI
- Alibaba Cloud Model Studio (DashScope)
- Azure OpenAI
- Groq
- Together.ai
- And many others
"""

import os
import logging
import json
import time
import traceback
from typing import List, Dict, Any, Iterator, Optional, AsyncIterator

try:
    from openai import OpenAI, AsyncOpenAI
except ImportError:
    raise ImportError(
        "OpenAI SDK not installed. Install with: pip install openai"
    )

# Try to import structured logging with get_logger
try:
    from src.observability import get_logger, ErrorCategory
    logger = get_logger("llm.openai_backend")
    STRUCTURED_LOGGING = True
except ImportError:
    # Fallback to stdlib logger
    logger = logging.getLogger(__name__)
    STRUCTURED_LOGGING = False
    class ErrorCategory:
        PROVIDER_TIMEOUT = 'provider_timeout'
        PROVIDER_ERROR = 'provider_error'

# Timeout constants (in seconds)
# Note: read timeout is configurable via LLMConfig.timeout for slow LLMs
DEFAULT_CONNECT_TIMEOUT = 10.0  # Time to establish connection
DEFAULT_WRITE_TIMEOUT = 10.0   # Time to send request
DEFAULT_POOL_TIMEOUT = 10.0    # Time to get connection from pool

from .base import (
    LLMBackend, LLMConfig, LLMResponse, StreamChunk, ToolDefinition,
    ProviderDelta, ToolCallDelta
)
# Use Session Model ToolCall as the canonical type
from src.session.models.message import ToolCall, ToolCallFunction
from .failure_handler import LLMFailureHandler
from .cache_tracker import CacheTracker


class OpenAIBackend(LLMBackend):
    """
    Generic OpenAI-compatible API backend.

    Supports any API that follows the OpenAI chat completions format.
    """

    def __init__(
        self,
        config: LLMConfig,
        api_key: Optional[str] = None,
        api_key_env: str = "OPENAI_API_KEY"
    ):
        """
        Initialize OpenAI-compatible backend.

        Args:
            config: LLM configuration
            api_key: API key (optional, will check environment if not provided)
            api_key_env: Environment variable name for API key (default: OPENAI_API_KEY)
        """
        super().__init__(config)

        # Get API key from parameter or environment variable
        self.api_key = api_key or os.getenv(api_key_env)
        if not self.api_key:
            raise ValueError(
                "API key not provided. Set an API key in the LLM config wizard "
                "(Ctrl+P > Configure LLM) or pass it via --api-key flag."
            )

        import httpx

        logger.info(
            f"OpenAI Backend Init - base_url: {config.base_url}, "
            f"key_provided: {bool(self.api_key)}"
        )

        # Initialize OpenAI client with base URL from config
        # Use httpx.Timeout for granular timeout control:
        # - connect: time to establish connection
        # - read: time between chunks (not total stream time)
        # - write: time to send request
        # - pool: time to get connection from pool
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=config.base_url,
            timeout=httpx.Timeout(
                connect=DEFAULT_CONNECT_TIMEOUT,
                read=config.timeout,
                write=DEFAULT_WRITE_TIMEOUT,
                pool=DEFAULT_POOL_TIMEOUT
            )
        )

        # Async client for non-blocking operations (TUI streaming)
        self.async_client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=config.base_url,
            timeout=httpx.Timeout(
                connect=DEFAULT_CONNECT_TIMEOUT,
                read=config.timeout,
                write=DEFAULT_WRITE_TIMEOUT,
                pool=DEFAULT_POOL_TIMEOUT
            )
        )

        # Initialize failure handler for robust error handling
        self.failure_handler = LLMFailureHandler(logger_instance=logger)

        # Prompt cache metrics tracker (accumulates across session)
        self.cache_tracker = CacheTracker()

    def log_cache_summary(self) -> None:
        """Log the session-level cache summary to the application log."""
        summary = self.cache_tracker.summary()
        if summary["total_calls"] > 0:
            logger.info(self.cache_tracker.format_summary())

    @staticmethod
    def _extract_cached_tokens(usage) -> Optional[int]:
        """Extract cached prompt tokens from usage object (returns None if unavailable)."""
        if not usage:
            return None
        details = getattr(usage, 'prompt_tokens_details', None)
        if details:
            val = getattr(details, 'cached_tokens', None)
            if val is not None and val > 0:
                return val
        return None

    def _is_anthropic_model(self) -> bool:
        """Check if the configured model is an Anthropic (Claude) model."""
        return "claude" in self.config.model_name.lower()

    @staticmethod
    def _add_cache_control_to_message(message: Dict[str, Any]) -> Dict[str, Any]:
        """Add cache_control breakpoint to a message's content.

        Converts plain string content to content blocks format with
        cache_control, which Anthropic requires for prompt caching.
        If content is already in blocks format, adds cache_control
        to the last block.
        """
        msg = message.copy()
        content = msg.get("content")

        if content is None:
            # Tool-call-only assistant messages have no content
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
            last_block = content[-1].copy()
            last_block["cache_control"] = {"type": "ephemeral"}
            msg["content"] = content[:-1] + [last_block]

        return msg

    def _apply_cache_control(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply Anthropic prompt caching breakpoints to messages.

        BP1: First system message (static across session)
        BP2: Second-to-last message (caches conversation history prefix)

        For non-Anthropic models, returns messages unchanged.
        """
        if not self._is_anthropic_model() or len(messages) < 2:
            return messages

        result = [m for m in messages]

        # BP1: First system message
        if result[0].get("role") == "system":
            result[0] = self._add_cache_control_to_message(result[0])

        # BP2: Walk backwards from second-to-last to find a message with
        # content (skips tool-call-only assistant messages with content=None)
        if len(result) >= 3:
            for i in range(len(result) - 2, 0, -1):
                if result[i].get("content") is not None:
                    result[i] = self._add_cache_control_to_message(result[i])
                    break

        return result

    def generate(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any
    ) -> LLMResponse:
        """
        Generate completion from messages.

        Args:
            messages: List of message dicts with 'role' and 'content'
            **kwargs: Additional generation parameters

        Returns:
            LLM response
        """
        self.validate_messages(messages)

        # Merge config parameters with kwargs
        params = {
            "model": self.config.model_name,
            "messages": self._apply_cache_control(messages),
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "top_p": kwargs.get("top_p", self.config.top_p),
            "stream": False,
        }

        # Wrap API call with failure handler (retry on transient errors)
        def api_call():
            return self.client.chat.completions.create(**params)

        try:
            response = self.failure_handler.execute_with_retry(
                api_call,
                max_attempts=3,
                backoff_base=2.0
            )

            # Extract content and metadata
            content = response.choices[0].message.content
            finish_reason = response.choices[0].finish_reason

            # Validate response
            if content:
                self.failure_handler.validate_response(content)

            # Track cache metrics
            self.cache_tracker.record(response.usage)
            cached = self._extract_cached_tokens(response.usage)
            logger.info(f"[CACHE] prompt={response.usage.prompt_tokens if response.usage else 0} cached={cached or 0}")

            # Build LLMResponse
            return LLMResponse(
                content=content,
                model=response.model,
                finish_reason=finish_reason,
                prompt_tokens=response.usage.prompt_tokens if response.usage else None,
                completion_tokens=response.usage.completion_tokens if response.usage else None,
                total_tokens=response.usage.total_tokens if response.usage else None,
                cached_tokens=cached,
                raw_response={
                    "id": response.id,
                    "created": response.created,
                }
            )

        except Exception as e:
            raise RuntimeError(f"OpenAI API error: {str(e)}") from e

    def generate_stream(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any
    ) -> Iterator[StreamChunk]:
        """
        Generate streaming completion.

        Args:
            messages: List of message dicts
            **kwargs: Additional parameters

        Yields:
            Stream chunks
        """
        self.validate_messages(messages)

        # Merge config parameters with kwargs
        params = {
            "model": self.config.model_name,
            "messages": self._apply_cache_control(messages),
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "top_p": kwargs.get("top_p", self.config.top_p),
            "stream": True,
        }

        # Request usage in stream for cache tracking
        if self.config.stream_usage:
            params["stream_options"] = {"include_usage": True}

        try:
            stream = self.client.chat.completions.create(**params)

            for chunk in stream:
                # Capture usage from any chunk that has it
                if hasattr(chunk, 'usage') and chunk.usage:
                    cached_tokens = self._extract_cached_tokens(chunk.usage)
                    self.cache_tracker.record(chunk.usage)
                    logger.info(f"[CACHE] prompt={chunk.usage.prompt_tokens} cached={cached_tokens or 0}")

                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    content = delta.content if delta.content else ""
                    finish_reason = chunk.choices[0].finish_reason

                    yield StreamChunk(
                        content=content,
                        done=finish_reason is not None,
                        model=chunk.model,
                        finish_reason=finish_reason,
                    )

        except Exception as e:
            raise RuntimeError(f"OpenAI streaming error: {str(e)}") from e

    def _parse_tool_arguments(self, arguments_str: str, tool_name: str) -> Dict[str, Any]:
        """Parse tool arguments JSON with robust error handling.

        Args:
            arguments_str: JSON string from LLM
            tool_name: Name of the tool (for logging)

        Returns:
            Parsed arguments dict (empty dict if parsing fails)
        """
        import json
        import re

        if not arguments_str or arguments_str.strip() == "":
            return {}

        # Try 1: Direct JSON parsing
        try:
            return json.loads(arguments_str)
        except json.JSONDecodeError as e:
            logger.warning(f"[JSON PARSE] Tool {tool_name} - Initial parse failed: {e}")

        # Try 2: Fix common issues
        try:
            # Fix unterminated strings by adding closing quotes
            fixed = arguments_str
            if fixed.count('"') % 2 != 0:
                fixed = fixed + '"'

            # Fix missing closing braces
            open_braces = fixed.count('{')
            close_braces = fixed.count('}')
            if open_braces > close_braces:
                fixed = fixed + ('}' * (open_braces - close_braces))

            # Try parsing fixed version
            return json.loads(fixed)
        except json.JSONDecodeError as e:
            logger.warning(f"[JSON PARSE] Tool {tool_name} - Fixed parse failed: {e}")

        # Try 3: Extract key-value pairs manually
        try:
            # Match "key": "value" or "key": value patterns
            pairs = re.findall(r'"([^"]+)":\s*(?:"([^"]*)"|([^,}\s]+))', arguments_str)
            result = {}
            for key, quoted_val, unquoted_val in pairs:
                result[key] = quoted_val if quoted_val else unquoted_val
            if result:
                logger.info(f"[JSON PARSE] Tool {tool_name} - Extracted {len(result)} key-value pairs")
                return result
        except Exception as e:
            logger.warning(f"[JSON PARSE] Tool {tool_name} - Regex extraction failed: {e}")

        # Fallback: Return empty dict
        logger.error(f"[JSON PARSE] Tool {tool_name} - All parsing attempts failed. Returning empty dict.")
        logger.debug(f"[JSON PARSE] Raw arguments: {arguments_str[:200]}")
        return {}

    def generate_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[ToolDefinition],
        tool_choice: str = "auto",
        **kwargs: Any
    ) -> LLMResponse:
        """
        Generate completion with tool calling support.

        This uses OpenAI's function calling API to enable structured tool calls.

        Args:
            messages: List of message dicts with 'role' and 'content'
            tools: List of available tools (function definitions)
            tool_choice: "auto" (LLM decides), "required" (must call tool),
                        "none" (no tools), or {"type": "function", "function": {"name": "..."}}
            **kwargs: Additional generation parameters

        Returns:
            LLMResponse with tool_calls field populated if LLM chose to call tools

        Example:
            tools = [ToolDefinition(...)]
            response = backend.generate_with_tools(messages, tools)
            if response.tool_calls:
                for call in response.tool_calls:
                    result = execute_tool(call.name, call.arguments)
        """
        self.validate_messages(messages)

        # Convert ToolDefinition objects to OpenAI function calling format
        tools_json = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters
                }
            }
            for tool in tools
        ]

        # Build parameters for API call
        params = {
            "model": self.config.model_name,
            "messages": self._apply_cache_control(messages),
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "top_p": kwargs.get("top_p", self.config.top_p),
            "tools": tools_json,
            "tool_choice": tool_choice,  # "auto", "required", "none", or specific tool
            "stream": False,
        }

        # Wrap API call with failure handler (retry on transient errors)
        def api_call():
            return self.client.chat.completions.create(**params)

        try:
            response = self.failure_handler.execute_with_retry(
                api_call,
                max_attempts=3,
                backoff_base=2.0
            )

            # Extract content and tool calls
            message = response.choices[0].message
            content = message.content  # May be None if tool-only response
            finish_reason = response.choices[0].finish_reason

            # Validate response if content is present
            if content:
                self.failure_handler.validate_response(content)

            # Track cache metrics
            self.cache_tracker.record(response.usage)
            logger.info(f"[CACHE] prompt={response.usage.prompt_tokens if response.usage else 0} cached={self._extract_cached_tokens(response.usage) or 0}")

            # Detect truncation
            truncation_info = {"truncated": False}
            if finish_reason == "length":
                logger.warning(
                    f"[TRUNCATION DETECTED] Response exceeded max_tokens limit. "
                    f"Tokens used: {response.usage.total_tokens if response.usage else 'unknown'}"
                )
                truncation_info = {
                    "truncated": True,
                    "finish_reason": "length",
                    "total_tokens": response.usage.total_tokens if response.usage else None,
                    "partial_tool_calls": len(message.tool_calls) if message.tool_calls else 0
                }

            # Parse tool calls if present
            tool_calls = None
            if message.tool_calls:
                tool_calls = []
                for tc in message.tool_calls:
                    # Parse arguments to validate/fix malformed JSON, then re-serialize
                    # Session Model ToolCall expects arguments as JSON string
                    parsed_args = self._parse_tool_arguments(tc.function.arguments, tc.function.name)
                    args_json = json.dumps(parsed_args) if isinstance(parsed_args, dict) else str(parsed_args)

                    tool_calls.append(
                        ToolCall(
                            id=tc.id,
                            function=ToolCallFunction(
                                name=tc.function.name,
                                arguments=args_json
                            )
                        )
                    )

            # Build LLMResponse with tool calls
            return LLMResponse(
                content=content,
                model=response.model,
                finish_reason=finish_reason,
                prompt_tokens=response.usage.prompt_tokens if response.usage else None,
                completion_tokens=response.usage.completion_tokens if response.usage else None,
                total_tokens=response.usage.total_tokens if response.usage else None,
                cached_tokens=self._extract_cached_tokens(response.usage),
                tool_calls=tool_calls,
                raw_response={
                    "id": response.id,
                    "created": response.created,
                    "truncation_info": truncation_info
                }
            )

        except Exception as e:
            raise RuntimeError(f"OpenAI tool calling API error: {str(e)}") from e

    def generate_with_tools_stream(
        self,
        messages: List[Dict[str, str]],
        tools: List[ToolDefinition],
        tool_choice: str = "auto",
        **kwargs: Any
    ) -> Iterator[tuple[StreamChunk, Optional[List[ToolCall]]]]:
        """
        Generate streaming completion with tool calling support.

        This enables streaming responses while using OpenAI's function calling API.
        Content is yielded as it arrives, and tool calls are accumulated and returned
        when the stream completes.

        Args:
            messages: List of message dicts with 'role' and 'content'
            tools: List of available tools (function definitions)
            tool_choice: "auto" (LLM decides), "required" (must call tool),
                        "none" (no tools), or {"type": "function", "function": {"name": "..."}}
            **kwargs: Additional generation parameters

        Yields:
            Tuple of (StreamChunk, Optional[List[ToolCall]]):
            - StreamChunk: Content chunk with done=False during streaming
            - None: Tool calls are None until stream completes

            Final yield when stream completes:
            - StreamChunk with done=True
            - List[ToolCall] if tools were called, else None

        Example:
            tools = [ToolDefinition(...)]
            for chunk, tool_calls in backend.generate_with_tools_stream(messages, tools):
                if not chunk.done:
                    print(chunk.content, end="", flush=True)
                else:
                    # Stream complete
                    if tool_calls:
                        for call in tool_calls:
                            result = execute_tool(call.name, call.arguments)
        """
        self.validate_messages(messages)

        # Convert ToolDefinition objects to OpenAI function calling format
        tools_json = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters
                }
            }
            for tool in tools
        ]

        # Build parameters for API call
        params = {
            "model": self.config.model_name,
            "messages": self._apply_cache_control(messages),
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "top_p": kwargs.get("top_p", self.config.top_p),
            "tools": tools_json,
            "tool_choice": tool_choice,
            "stream": True,  # Enable streaming
        }

        # Add stream_options for usage tracking (OpenAI-specific, may not work with all providers)
        if getattr(self.config, 'stream_usage', True):
            params["stream_options"] = {"include_usage": True}

        # Initialize stream variable before try block to ensure cleanup works
        stream = None
        try:
            stream = self.client.chat.completions.create(**params)

            # Accumulate tool calls by index (for parallel calls)
            tool_calls_accumulator: Dict[int, Dict[str, Any]] = {}
            finish_reason = None
            model_name = None
            # Token usage (captured from final chunk with stream_options.include_usage)
            prompt_tokens = None
            completion_tokens = None
            total_tokens = None
            cached_tokens = None

            try:
                for chunk in stream:
                    # Capture usage from any chunk that has it (comes after finish_reason)
                    if hasattr(chunk, 'usage') and chunk.usage:
                        prompt_tokens = chunk.usage.prompt_tokens
                        completion_tokens = chunk.usage.completion_tokens
                        total_tokens = chunk.usage.total_tokens
                        cached_tokens = self._extract_cached_tokens(chunk.usage)
                        self.cache_tracker.record(chunk.usage)
                        logger.info(f"[CACHE] prompt={prompt_tokens} cached={cached_tokens or 0}")

                    # Skip chunks with no choices (e.g., usage-only chunks)
                    if not chunk.choices or len(chunk.choices) == 0:
                        continue

                    delta = chunk.choices[0].delta
                    finish_reason = chunk.choices[0].finish_reason
                    model_name = chunk.model

                    # Yield text content chunks as they arrive
                    if delta.content:
                        yield (
                            StreamChunk(
                                content=delta.content,
                                done=False,
                                model=model_name,
                                finish_reason=None
                            ),
                            None  # No tool calls yet during streaming
                        )

                    # Accumulate tool call deltas
                    if delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index

                            # Initialize accumulator for this tool call index
                            if idx not in tool_calls_accumulator:
                                tool_calls_accumulator[idx] = {
                                    "id": "",
                                    "name": "",
                                    "arguments": ""
                                }

                            # Accumulate ID (comes in first chunk for this index)
                            if tc_delta.id:
                                tool_calls_accumulator[idx]["id"] = tc_delta.id

                            # Accumulate function name (comes in first chunk)
                            if tc_delta.function and tc_delta.function.name:
                                tool_calls_accumulator[idx]["name"] = tc_delta.function.name

                            # Accumulate function arguments (comes in multiple chunks)
                            if tc_delta.function and tc_delta.function.arguments:
                                tool_calls_accumulator[idx]["arguments"] += tc_delta.function.arguments

            finally:
                # CRITICAL: Always close stream to release HTTP connection
                if stream is not None and hasattr(stream, 'close'):
                    stream.close()

            # Stream complete - parse accumulated tool calls
            tool_calls = None
            if tool_calls_accumulator:
                tool_calls = []
                for idx in sorted(tool_calls_accumulator.keys()):
                    tc_data = tool_calls_accumulator[idx]

                    # Parse accumulated JSON arguments, then re-serialize
                    # Session Model ToolCall expects arguments as JSON string
                    parsed_args = self._parse_tool_arguments(
                        tc_data["arguments"],
                        tc_data["name"]
                    )
                    args_json = json.dumps(parsed_args) if isinstance(parsed_args, dict) else str(parsed_args)

                    tool_calls.append(
                        ToolCall(
                            id=tc_data["id"],
                            function=ToolCallFunction(
                                name=tc_data["name"],
                                arguments=args_json
                            )
                        )
                    )

            # Yield final chunk with tool calls and usage
            yield (
                StreamChunk(
                    content="",  # No more content
                    done=True,
                    model=model_name,
                    finish_reason=finish_reason,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    cached_tokens=cached_tokens,
                ),
                tool_calls
            )

        except Exception as e:
            # Extract error details
            error_type = type(e).__name__
            error_msg = str(e).strip() or repr(e)

            # Determine error category
            is_timeout = 'timeout' in error_type.lower()
            category = ErrorCategory.PROVIDER_TIMEOUT if is_timeout else ErrorCategory.PROVIDER_ERROR

            # Find root cause in exception chain
            root_cause = e
            while root_cause.__cause__ is not None:
                root_cause = root_cause.__cause__
            root_cause_type = type(root_cause).__name__
            root_cause_message = str(root_cause).strip()[:500]

            # Log with structlog key=value pattern including timeout debugging fields
            logger.exception(
                "openai_streaming_error",
                category=category,
                error_type=error_type,
                model=self.config.model_name,
                backend="openai",
                operation="generate_with_tools_stream",
                timeout_read_s=self.config.timeout,
                timeout_write_s=DEFAULT_WRITE_TIMEOUT,
                timeout_connect_s=DEFAULT_CONNECT_TIMEOUT,
                timeout_pool_s=DEFAULT_POOL_TIMEOUT,
                root_cause_type=root_cause_type,
                root_cause_message=root_cause_message,
            )

            raise RuntimeError(
                f"OpenAI streaming tool calling error: {error_type}: {error_msg}"
            ) from e

    async def generate_with_tools_stream_async(
        self,
        messages: List[Dict[str, str]],
        tools: List[ToolDefinition],
        tool_choice: str = "auto",
        **kwargs: Any
    ) -> AsyncIterator[tuple[StreamChunk, Optional[List[ToolCall]]]]:
        """
        Generate async streaming completion with tool calling support.

        This is the async version of generate_with_tools_stream() for use with
        asyncio-based applications like the TUI chat interface.

        Content is yielded as it arrives, and tool calls are accumulated and returned
        when the stream completes.

        Args:
            messages: List of message dicts with 'role' and 'content'
            tools: List of available tools (function definitions)
            tool_choice: "auto" (LLM decides), "required" (must call tool),
                        "none" (no tools), or {"type": "function", "function": {"name": "..."}}
            **kwargs: Additional generation parameters

        Yields:
            Tuple of (StreamChunk, Optional[List[ToolCall]]):
            - StreamChunk: Content chunk with done=False during streaming
            - None: Tool calls are None until stream completes

            Final yield when stream completes:
            - StreamChunk with done=True
            - List[ToolCall] if tools were called, else None

        Example:
            tools = [ToolDefinition(...)]
            async for chunk, tool_calls in backend.generate_with_tools_stream_async(messages, tools):
                if not chunk.done:
                    print(chunk.content, end="", flush=True)
                else:
                    # Stream complete
                    if tool_calls:
                        for call in tool_calls:
                            result = await execute_tool_async(call.name, call.arguments)
        """
        self.validate_messages(messages)

        # Convert ToolDefinition objects to OpenAI function calling format
        tools_json = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters
                }
            }
            for tool in tools
        ]

        # Build parameters for API call
        params = {
            "model": self.config.model_name,
            "messages": self._apply_cache_control(messages),
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "top_p": kwargs.get("top_p", self.config.top_p),
            "tools": tools_json,
            "tool_choice": tool_choice,
            "stream": True,  # Enable streaming
        }

        # Add stream_options for usage tracking (OpenAI-specific, may not work with all providers)
        if getattr(self.config, 'stream_usage', True):
            params["stream_options"] = {"include_usage": True}

        # Initialize stream variable before try block to ensure cleanup works
        stream = None
        try:
            # Use async client for non-blocking API call
            stream = await self.async_client.chat.completions.create(**params)

            # Accumulate tool calls by index (for parallel calls)
            tool_calls_accumulator: Dict[int, Dict[str, Any]] = {}
            finish_reason = None
            model_name = None
            # Token usage (captured from final chunk with stream_options.include_usage)
            prompt_tokens = None
            completion_tokens = None
            total_tokens = None
            cached_tokens = None

            try:
                async for chunk in stream:
                    # Capture usage from any chunk that has it (comes after finish_reason)
                    if hasattr(chunk, 'usage') and chunk.usage:
                        prompt_tokens = chunk.usage.prompt_tokens
                        completion_tokens = chunk.usage.completion_tokens
                        total_tokens = chunk.usage.total_tokens
                        cached_tokens = self._extract_cached_tokens(chunk.usage)
                        self.cache_tracker.record(chunk.usage)
                        logger.info(f"[CACHE] prompt={prompt_tokens} cached={cached_tokens or 0}")

                    # Skip chunks with no choices (e.g., usage-only chunks)
                    if not chunk.choices or len(chunk.choices) == 0:
                        continue

                    delta = chunk.choices[0].delta
                    finish_reason = chunk.choices[0].finish_reason
                    model_name = chunk.model

                    # Yield text content chunks as they arrive
                    if delta.content:
                        yield (
                            StreamChunk(
                                content=delta.content,
                                done=False,
                                model=model_name,
                                finish_reason=None
                            ),
                            None  # No tool calls yet during streaming
                        )

                    # Accumulate tool call deltas
                    if delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index

                            # Initialize accumulator for this tool call index
                            if idx not in tool_calls_accumulator:
                                tool_calls_accumulator[idx] = {
                                    "id": "",
                                    "name": "",
                                    "arguments": ""
                                }

                            # Accumulate ID (comes in first chunk for this index)
                            if tc_delta.id:
                                tool_calls_accumulator[idx]["id"] = tc_delta.id

                            # Accumulate function name (comes in first chunk)
                            if tc_delta.function and tc_delta.function.name:
                                tool_calls_accumulator[idx]["name"] = tc_delta.function.name

                            # Accumulate function arguments (comes in multiple chunks)
                            if tc_delta.function and tc_delta.function.arguments:
                                tool_calls_accumulator[idx]["arguments"] += tc_delta.function.arguments

            finally:
                # CRITICAL: Always close stream to release HTTP connection
                if stream is not None and hasattr(stream, 'close'):
                    await stream.close()

            # Stream complete - parse accumulated tool calls
            tool_calls = None
            if tool_calls_accumulator:
                tool_calls = []
                for idx in sorted(tool_calls_accumulator.keys()):
                    tc_data = tool_calls_accumulator[idx]

                    # Parse accumulated JSON arguments, then re-serialize
                    # Session Model ToolCall expects arguments as JSON string
                    parsed_args = self._parse_tool_arguments(
                        tc_data["arguments"],
                        tc_data["name"]
                    )
                    args_json = json.dumps(parsed_args) if isinstance(parsed_args, dict) else str(parsed_args)

                    tool_calls.append(
                        ToolCall(
                            id=tc_data["id"],
                            function=ToolCallFunction(
                                name=tc_data["name"],
                                arguments=args_json
                            )
                        )
                    )

            # Yield final chunk with tool calls and usage
            yield (
                StreamChunk(
                    content="",  # No more content
                    done=True,
                    model=model_name,
                    finish_reason=finish_reason,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    cached_tokens=cached_tokens,
                ),
                tool_calls
            )

        except Exception as e:
            # Extract error details
            error_type = type(e).__name__
            error_msg = str(e).strip() or repr(e)

            # Determine error category
            is_timeout = 'timeout' in error_type.lower()
            category = ErrorCategory.PROVIDER_TIMEOUT if is_timeout else ErrorCategory.PROVIDER_ERROR

            # Find root cause in exception chain
            root_cause = e
            while root_cause.__cause__ is not None:
                root_cause = root_cause.__cause__
            root_cause_type = type(root_cause).__name__
            root_cause_message = str(root_cause).strip()[:500]

            # Log with structlog key=value pattern including timeout debugging fields
            logger.exception(
                "openai_async_streaming_error",
                category=category,
                error_type=error_type,
                model=self.config.model_name,
                backend="openai",
                operation="generate_with_tools_stream_async",
                timeout_read_s=self.config.timeout,
                timeout_write_s=DEFAULT_WRITE_TIMEOUT,
                timeout_connect_s=DEFAULT_CONNECT_TIMEOUT,
                timeout_pool_s=DEFAULT_POOL_TIMEOUT,
                root_cause_type=root_cause_type,
                root_cause_message=root_cause_message,
            )

            raise RuntimeError(
                f"OpenAI async streaming tool calling error: {error_type}: {error_msg}"
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
        **kwargs: Any
    ) -> Iterator[ProviderDelta]:
        """
        Generate streaming completion as ProviderDelta objects.

        This is the canonical interface for the Unified Persistence Architecture.
        Emits raw deltas that can be consumed by StreamingPipeline.

        Args:
            messages: List of message dicts with 'role' and 'content'
            tools: Optional list of tools (function definitions)
            tool_choice: "auto", "required", "none", or specific tool
            stream_id: Optional stream ID (auto-generated if not provided)
            **kwargs: Additional generation parameters

        Yields:
            ProviderDelta objects with text_delta, tool_call_delta, finish_reason, usage

        Example:
            >>> for delta in backend.generate_provider_deltas(messages, tools):
            ...     message = pipeline.process_delta(delta)
            ...     if message:
            ...         print(f"Complete: {len(message.segments)} segments")
        """
        from src.session.models.base import generate_stream_id

        self.validate_messages(messages)
        sid = stream_id or generate_stream_id()

        # Build parameters
        params = {
            "model": self.config.model_name,
            "messages": self._apply_cache_control(messages),
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "top_p": kwargs.get("top_p", self.config.top_p),
            "stream": True,
        }

        # Add tools if provided
        if tools:
            params["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters
                    }
                }
                for tool in tools
            ]
            params["tool_choice"] = tool_choice

        # Add stream_options for usage tracking
        if getattr(self.config, 'stream_usage', True):
            params["stream_options"] = {"include_usage": True}

        stream = None
        try:
            stream = self.client.chat.completions.create(**params)

            # Track tool call accumulation by index
            tool_call_ids: Dict[int, str] = {}
            tool_call_names: Dict[int, str] = {}
            finish_reason = None
            usage_dict = None

            try:
                for chunk in stream:
                    # Capture usage
                    if hasattr(chunk, 'usage') and chunk.usage:
                        usage_dict = {
                            "input_tokens": chunk.usage.prompt_tokens,
                            "output_tokens": chunk.usage.completion_tokens,
                            "cached_tokens": self._extract_cached_tokens(chunk.usage),
                        }
                        self.cache_tracker.record(chunk.usage)
                        logger.info(f"[CACHE] prompt={chunk.usage.prompt_tokens} cached={usage_dict['cached_tokens'] or 0}")

                    # Skip chunks with no choices
                    if not chunk.choices or len(chunk.choices) == 0:
                        continue

                    delta = chunk.choices[0].delta
                    finish_reason = chunk.choices[0].finish_reason

                    # Emit text delta
                    if delta.content:
                        yield ProviderDelta(
                            stream_id=sid,
                            text_delta=delta.content,
                        )

                    # Emit tool call deltas
                    if delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index

                            # Track ID and name for this index
                            if tc_delta.id:
                                tool_call_ids[idx] = tc_delta.id
                            if tc_delta.function and tc_delta.function.name:
                                tool_call_names[idx] = tc_delta.function.name

                            # Emit tool call delta
                            yield ProviderDelta(
                                stream_id=sid,
                                tool_call_delta=ToolCallDelta(
                                    index=idx,
                                    id=tc_delta.id if tc_delta.id else None,
                                    name=tc_delta.function.name if tc_delta.function and tc_delta.function.name else None,
                                    arguments_delta=tc_delta.function.arguments if tc_delta.function and tc_delta.function.arguments else "",
                                ),
                            )

            finally:
                if stream is not None and hasattr(stream, 'close'):
                    stream.close()

            # Emit final delta with finish_reason and usage
            yield ProviderDelta(
                stream_id=sid,
                finish_reason=finish_reason or "stop",
                usage=usage_dict,
            )

        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e).strip() or repr(e)
            logger.exception(
                "openai_provider_delta_error",
                error_type=error_type,
                model=self.config.model_name,
            )
            raise RuntimeError(f"OpenAI provider delta error: {error_type}: {error_msg}") from e

    async def generate_provider_deltas_async(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[ToolDefinition]] = None,
        tool_choice: str = "auto",
        stream_id: Optional[str] = None,
        **kwargs: Any
    ) -> AsyncIterator[ProviderDelta]:
        """
        Generate async streaming completion as ProviderDelta objects.

        This is the async version of generate_provider_deltas() for use with
        asyncio-based applications like the TUI.

        Args:
            messages: List of message dicts with 'role' and 'content'
            tools: Optional list of tools (function definitions)
            tool_choice: "auto", "required", "none", or specific tool
            stream_id: Optional stream ID (auto-generated if not provided)
            **kwargs: Additional generation parameters

        Yields:
            ProviderDelta objects with text_delta, tool_call_delta, finish_reason, usage

        Example:
            >>> async for delta in backend.generate_provider_deltas_async(messages, tools):
            ...     message = pipeline.process_delta(delta)
            ...     if message:
            ...         print(f"Complete: {len(message.segments)} segments")
        """
        from src.session.models.base import generate_stream_id

        self.validate_messages(messages)
        sid = stream_id or generate_stream_id()

        # Build parameters
        params = {
            "model": self.config.model_name,
            "messages": self._apply_cache_control(messages),
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "top_p": kwargs.get("top_p", self.config.top_p),
            "stream": True,
        }

        # Add tools if provided
        if tools:
            params["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters
                    }
                }
                for tool in tools
            ]
            params["tool_choice"] = tool_choice

        # Add stream_options for usage tracking
        if getattr(self.config, 'stream_usage', True):
            params["stream_options"] = {"include_usage": True}

        stream = None
        try:
            stream = await self.async_client.chat.completions.create(**params)

            # Track tool call accumulation by index
            tool_call_ids: Dict[int, str] = {}
            tool_call_names: Dict[int, str] = {}
            finish_reason = None
            usage_dict = None

            try:
                async for chunk in stream:
                    # Capture usage
                    if hasattr(chunk, 'usage') and chunk.usage:
                        usage_dict = {
                            "input_tokens": chunk.usage.prompt_tokens,
                            "output_tokens": chunk.usage.completion_tokens,
                            "cached_tokens": self._extract_cached_tokens(chunk.usage),
                        }
                        self.cache_tracker.record(chunk.usage)
                        logger.info(f"[CACHE] prompt={chunk.usage.prompt_tokens} cached={usage_dict['cached_tokens'] or 0}")

                    # Skip chunks with no choices
                    if not chunk.choices or len(chunk.choices) == 0:
                        continue

                    delta = chunk.choices[0].delta
                    finish_reason = chunk.choices[0].finish_reason

                    # Emit text delta
                    if delta.content:
                        yield ProviderDelta(
                            stream_id=sid,
                            text_delta=delta.content,
                        )

                    # Emit tool call deltas
                    if delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index

                            # Track ID and name for this index
                            if tc_delta.id:
                                tool_call_ids[idx] = tc_delta.id
                            if tc_delta.function and tc_delta.function.name:
                                tool_call_names[idx] = tc_delta.function.name

                            # Emit tool call delta
                            yield ProviderDelta(
                                stream_id=sid,
                                tool_call_delta=ToolCallDelta(
                                    index=idx,
                                    id=tc_delta.id if tc_delta.id else None,
                                    name=tc_delta.function.name if tc_delta.function and tc_delta.function.name else None,
                                    arguments_delta=tc_delta.function.arguments if tc_delta.function and tc_delta.function.arguments else "",
                                ),
                            )

            finally:
                if stream is not None and hasattr(stream, 'close'):
                    await stream.close()

            # Emit final delta with finish_reason and usage
            yield ProviderDelta(
                stream_id=sid,
                finish_reason=finish_reason or "stop",
                usage=usage_dict,
            )

        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e).strip() or repr(e)
            logger.exception(
                "openai_async_provider_delta_error",
                error_type=error_type,
                model=self.config.model_name,
            )
            raise RuntimeError(f"OpenAI async provider delta error: {error_type}: {error_msg}") from e

    def count_tokens(self, text: str) -> int:
        """
        Count tokens in text.

        Note: This is an approximation. For accurate counting,
        use tiktoken library with the appropriate model encoding.

        Args:
            text: Text to count tokens

        Returns:
            Approximate token count
        """
        # Rough estimate: ~4 chars per token for English
        # This is a conservative estimate that works across languages
        return len(text) // 4

    def is_available(self) -> bool:
        """
        Check if backend is available.

        Returns:
            True if backend is ready
        """
        try:
            # Try to list models as a health check
            self.client.models.list()
            return True
        except Exception as e:
            logger.error(f"Backend availability check failed: {type(e).__name__}: {str(e)}")
            return False

    def list_models(self) -> List[str]:
        """
        List available models.

        Returns:
            List of model names
        """
        try:
            models_response = self.client.models.list()
            return [model.id for model in models_response.data]
        except Exception:
            # If listing fails, return empty list
            # Different providers have different model listing support
            return []
