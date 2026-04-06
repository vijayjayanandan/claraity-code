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
    "ModelConfig",
    "get_model_config",
]
