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
from typing import List, Dict, Any, Iterator, Optional

try:
    from openai import OpenAI
except ImportError:
    raise ImportError(
        "OpenAI SDK not installed. Install with: pip install openai"
    )

logger = logging.getLogger(__name__)

from .base import LLMBackend, LLMConfig, LLMResponse, StreamChunk, ToolDefinition, ToolCall


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
                f"API key not provided. Set {api_key_env} environment variable "
                f"or pass api_key parameter."
            )

        # Initialize OpenAI client with custom base URL if provided
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=config.base_url if config.base_url != "http://localhost:11434" else None,
            timeout=config.timeout
        )

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
            "messages": messages,
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "top_p": kwargs.get("top_p", self.config.top_p),
            "stream": False,
        }

        try:
            response = self.client.chat.completions.create(**params)

            # Extract content and metadata
            content = response.choices[0].message.content
            finish_reason = response.choices[0].finish_reason

            # Build LLMResponse
            return LLMResponse(
                content=content,
                model=response.model,
                finish_reason=finish_reason,
                prompt_tokens=response.usage.prompt_tokens if response.usage else None,
                completion_tokens=response.usage.completion_tokens if response.usage else None,
                total_tokens=response.usage.total_tokens if response.usage else None,
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
            "messages": messages,
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "top_p": kwargs.get("top_p", self.config.top_p),
            "stream": True,
        }

        try:
            stream = self.client.chat.completions.create(**params)

            for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    content = delta.content if delta.content else ""
                    finish_reason = chunk.choices[0].finish_reason

                    yield StreamChunk(
                        content=content,
                        done=finish_reason is not None,
                        model=chunk.model,
                        finish_reason=finish_reason
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
            "messages": messages,
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "top_p": kwargs.get("top_p", self.config.top_p),
            "tools": tools_json,
            "tool_choice": tool_choice,  # "auto", "required", "none", or specific tool
            "stream": False,
        }

        try:
            response = self.client.chat.completions.create(**params)

            # Extract content and tool calls
            message = response.choices[0].message
            content = message.content  # May be None if tool-only response
            finish_reason = response.choices[0].finish_reason

            # Parse tool calls if present
            tool_calls = None
            if message.tool_calls:
                tool_calls = []
                for tc in message.tool_calls:
                    # Parse arguments (they come as JSON string from API)
                    # Use robust parsing to handle LLM-generated JSON errors
                    arguments = self._parse_tool_arguments(tc.function.arguments, tc.function.name)

                    tool_calls.append(
                        ToolCall(
                            id=tc.id,
                            name=tc.function.name,
                            arguments=arguments  # Already a dict
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
                tool_calls=tool_calls,
                raw_response={
                    "id": response.id,
                    "created": response.created,
                }
            )

        except Exception as e:
            raise RuntimeError(f"OpenAI tool calling API error: {str(e)}") from e

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
        except Exception:
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
