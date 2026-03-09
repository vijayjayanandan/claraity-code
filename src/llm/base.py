"""Base LLM interface and models."""

import os
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterator
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from src.session.models.message import TokenUsage as SessionTokenUsage

# Import Session Model ToolCall as the canonical type
from src.session.models.message import ToolCall


class LLMBackendType(str, Enum):
    """Supported LLM backend types."""

    OLLAMA = "ollama"
    VLLM = "vllm"
    LOCALAI = "localai"
    LLAMACPP = "llamacpp"
    OPENAI = "openai"  # Generic OpenAI-compatible API
    ANTHROPIC = "anthropic"  # Native Anthropic Messages API


class LLMConfig(BaseModel):
    """Configuration for LLM backend. All values should come from .env file."""

    model_config = ConfigDict(protected_namespaces=(), use_enum_values=True)

    backend_type: LLMBackendType
    model_name: str
    base_url: str

    # Generation parameters (no defaults - must be provided)
    temperature: float
    max_tokens: int
    top_p: float
    top_k: int = Field(default_factory=lambda: int(os.getenv("LLM_TOP_K", "40")))
    repeat_penalty: float = Field(
        default_factory=lambda: float(os.getenv("LLM_REPEAT_PENALTY", "1.1"))
    )

    # Extended thinking (Claude, etc.)
    thinking_budget: int | None = None  # Token budget for thinking blocks

    # Context settings
    context_window: int
    num_ctx: int | None = None  # Override context window

    # Performance
    num_predict: int | None = None
    num_gpu: int | None = None
    num_thread: int | None = None

    # Streaming
    stream: bool = Field(
        default_factory=lambda: os.getenv("ENABLE_STREAMING", "true").lower() == "true"
    )
    # Stream usage tracking (OpenAI-specific, may not work with all providers)
    stream_usage: bool = Field(
        default_factory=lambda: os.getenv("STREAM_USAGE", "true").lower() == "true"
    )

    # Timeout
    timeout: float = Field(default_factory=lambda: float(os.getenv("REQUEST_TIMEOUT", "300")))


class ToolParameter(BaseModel):
    """Tool parameter definition (JSON Schema format)."""

    type: str  # "string", "number", "boolean", "array", "object"
    description: str
    enum: list[str] | None = None
    items: dict[str, Any] | None = None  # For array types
    properties: dict[str, Any] | None = None  # For object types
    required: list[str] | None = None  # For object types


class ToolDefinition(BaseModel):
    """Tool definition for LLM (OpenAI function calling format)."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema object

    class Config:
        # Pydantic V2: renamed from schema_extra to json_schema_extra
        json_schema_extra = {
            "example": {
                "name": "write_file",
                "description": "Create a new file with content",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Path to file"},
                        "content": {"type": "string", "description": "File content"},
                    },
                    "required": ["file_path", "content"],
                },
            }
        }


# ToolCall imported from src.session.models.message (canonical type)
# Removed redundant LLM Backend ToolCall class - use Session Model ToolCall


class LLMResponse(BaseModel):
    """Response from LLM."""

    content: str | None = None  # Optional because tool-only responses may have no text
    model: str
    finish_reason: str | None = None

    # Token usage
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cached_tokens: int | None = None  # Prompt tokens served from cache

    # Timing
    eval_duration: float | None = None  # seconds

    # Raw response
    raw_response: dict[str, Any] | None = None

    # Tool calls (for tool calling mode)
    tool_calls: list[ToolCall] | None = None


class StreamChunk(BaseModel):
    """Chunk from streaming response."""

    content: str
    done: bool = False
    model: str | None = None
    finish_reason: str | None = None

    # Token usage (populated on final chunk when done=True)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cached_tokens: int | None = None  # Prompt tokens served from cache


# =============================================================================
# Provider Delta Contract (Unified Persistence Architecture)
# =============================================================================


class ToolCallDelta(BaseModel):
    """
    Incremental tool call data from provider.

    Used during streaming to accumulate tool call information
    before the full tool call is complete.
    """

    index: int  # Tool call index in current message
    id: str | None = None  # Tool call ID (first delta only)
    name: str | None = None  # Function name (first delta only)
    arguments_delta: str = ""  # JSON arguments chunk (accumulated)


class ProviderDelta(BaseModel):
    """
    Raw delta from LLM provider - the canonical input to StreamingPipeline.

    This is the contract between provider adapters and the streaming pipeline.
    Providers MUST emit ProviderDelta objects. They MUST NOT:
    - Parse markdown or code fences
    - Decide message boundaries (except finish_reason)
    - Emit UI events or segments
    - Make structural decisions

    The StreamingPipeline is the ONLY place that converts these raw deltas
    into structured segments (TextSegment, CodeBlockSegment, etc.).
    """

    stream_id: str  # Self-describing, stable across deltas
    text_delta: str | None = None  # Raw text chunk
    tool_call_delta: ToolCallDelta | None = None  # Incremental tool call
    thinking_delta: str | None = None  # Native thinking (if provider supports)
    thinking_signature: str | None = None  # Thinking block signature (Anthropic)
    finish_reason: str | None = None  # "stop", "tool_calls", etc.
    usage: dict[str, Any] | None = None  # Token counts as dict (on finish)

    class Config:
        arbitrary_types_allowed = True


class LLMBackend(ABC):
    """Abstract base class for LLM backends."""

    def __init__(self, config: LLMConfig):
        """
        Initialize LLM backend.

        Args:
            config: LLM configuration
        """
        self.config = config

    @abstractmethod
    def generate(self, messages: list[dict[str, str]], **kwargs: Any) -> LLMResponse:
        """
        Generate completion from messages.

        Args:
            messages: list of message dicts with 'role' and 'content'
            **kwargs: Additional generation parameters

        Returns:
            LLM response
        """
        pass

    @abstractmethod
    def generate_stream(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> Iterator[StreamChunk]:
        """
        Generate streaming completion.

        Args:
            messages: list of message dicts
            **kwargs: Additional parameters

        Yields:
            Stream chunks
        """
        pass

    def generate_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[ToolDefinition],
        tool_choice: str = "auto",
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Generate completion with tool calling support.

        This method enables the LLM to call tools (functions) as part of its response.
        The LLM can choose to call one or more tools, or respond with text.

        Args:
            messages: list of message dicts with 'role' and 'content'
            tools: list of available tools (function definitions)
            tool_choice: "auto" (LLM decides), "required" (must call tool),
                        "none" (no tools), or specific tool name
            **kwargs: Additional generation parameters

        Returns:
            LLM response with optional tool_calls field

        Raises:
            NotImplementedError: If backend doesn't support tool calling

        Example:
            tools = [
                ToolDefinition(
                    name="write_file",
                    description="Create a new file",
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path"},
                            "content": {"type": "string", "description": "Content"}
                        },
                        "required": ["path", "content"]
                    }
                )
            ]
            response = backend.generate_with_tools(messages, tools)
            if response.tool_calls:
                for call in response.tool_calls:
                    print(f"Call {call.name} with {call.arguments}")
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support tool calling. "
            "Use OpenAIBackend or implement generate_with_tools() method."
        )

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """
        Count tokens in text.

        Args:
            text: Text to count tokens

        Returns:
            Token count
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if backend is available.

        Returns:
            True if backend is ready
        """
        pass

    @abstractmethod
    def list_models(self) -> list[str]:
        """
        list available models.

        Returns:
            list of model names
        """
        pass

    def validate_messages(self, messages: list[dict[str, str]]) -> None:
        """
        Validate message format.

        Args:
            messages: Messages to validate

        Raises:
            ValueError: If messages are invalid
        """
        if not messages:
            raise ValueError("Messages cannot be empty")

        for msg in messages:
            if "role" not in msg:
                raise ValueError("Each message must have 'role'")

            # Content is optional for assistant messages with tool_calls and tool messages
            if msg["role"] not in ["assistant", "tool"] and "content" not in msg:
                raise ValueError(f"Message with role '{msg['role']}' must have 'content'")

            if msg["role"] not in ["system", "user", "assistant", "tool"]:
                raise ValueError(f"Invalid role: {msg['role']}")

    def format_prompt(self, messages: list[dict[str, str]]) -> str:
        """
        Format messages into a single prompt string.
        Useful for backends that don't support chat format.

        Args:
            messages: list of messages

        Returns:
            Formatted prompt string
        """
        prompt_parts = []

        for msg in messages:
            role = msg["role"]
            content = msg["content"]

            if role == "system":
                prompt_parts.append(f"<|system|>\n{content}\n")
            elif role == "user":
                prompt_parts.append(f"<|user|>\n{content}\n")
            elif role == "assistant":
                prompt_parts.append(f"<|assistant|>\n{content}\n")

        prompt_parts.append("<|assistant|>\n")
        return "".join(prompt_parts)
