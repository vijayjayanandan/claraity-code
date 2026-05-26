"""LLM backend integrations for the AI coding agent."""

from .base import (
    LLMBackend,
    LLMBackendType,
    LLMConfig,
    LLMResponse,
    ToolCall,
    ToolDefinition,
    ToolParameter,
)
from .model_config import ModelConfig, get_model_config
from .openai_backend import OpenAIBackend

# Lazy import: AnthropicBackend requires `anthropic` SDK (optional dependency)
try:
    from .anthropic_backend import AnthropicBackend
except ImportError:
    AnthropicBackend = None  # type: ignore[assignment,misc]

# Lazy import: OpenAINativeBackend requires openai>=2.34.0
try:
    from .openai_native_backend import OpenAINativeBackend
except ImportError:
    OpenAINativeBackend = None  # type: ignore[assignment,misc]

from .backend_factory import create_backend

__all__ = [
    "LLMBackend",
    "LLMBackendType",
    "LLMConfig",
    "LLMResponse",
    "ToolDefinition",
    "ToolCall",
    "ToolParameter",
    "OpenAIBackend",
    "AnthropicBackend",
    "OpenAINativeBackend",
    "ModelConfig",
    "get_model_config",
    "create_backend",
]
