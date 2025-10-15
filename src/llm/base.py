"""Base LLM interface and models."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, AsyncIterator, Iterator
from pydantic import BaseModel, Field
from enum import Enum


class LLMBackendType(str, Enum):
    """Supported LLM backend types."""

    OLLAMA = "ollama"
    VLLM = "vllm"
    LOCALAI = "localai"
    LLAMACPP = "llamacpp"
    OPENAI = "openai"  # Generic OpenAI-compatible API


class LLMConfig(BaseModel):
    """Configuration for LLM backend."""

    backend_type: LLMBackendType
    model_name: str
    base_url: str = "http://localhost:11434"

    # Generation parameters
    temperature: float = 0.2
    max_tokens: int = 2048
    top_p: float = 0.95
    top_k: int = 40
    repeat_penalty: float = 1.1

    # Context settings
    context_window: int = 4096
    num_ctx: Optional[int] = None  # Override context window

    # Performance
    num_predict: Optional[int] = None
    num_gpu: Optional[int] = None
    num_thread: Optional[int] = None

    # Streaming
    stream: bool = True

    # Timeout
    timeout: float = 300.0  # 5 minutes for complex RAG queries

    class Config:
        use_enum_values = True


class LLMResponse(BaseModel):
    """Response from LLM."""

    content: str
    model: str
    finish_reason: Optional[str] = None

    # Token usage
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None

    # Timing
    eval_duration: Optional[float] = None  # seconds

    # Raw response
    raw_response: Optional[Dict[str, Any]] = None


class StreamChunk(BaseModel):
    """Chunk from streaming response."""

    content: str
    done: bool = False
    model: Optional[str] = None
    finish_reason: Optional[str] = None


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
        pass

    @abstractmethod
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
        pass

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
    def list_models(self) -> List[str]:
        """
        List available models.

        Returns:
            List of model names
        """
        pass

    def validate_messages(self, messages: List[Dict[str, str]]) -> None:
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
            if "role" not in msg or "content" not in msg:
                raise ValueError("Each message must have 'role' and 'content'")

            if msg["role"] not in ["system", "user", "assistant"]:
                raise ValueError(f"Invalid role: {msg['role']}")

    def format_prompt(self, messages: List[Dict[str, str]]) -> str:
        """
        Format messages into a single prompt string.
        Useful for backends that don't support chat format.

        Args:
            messages: List of messages

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
