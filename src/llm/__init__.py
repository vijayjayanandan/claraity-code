"""LLM backend integrations for the AI coding agent."""

from .base import (
    LLMBackend,
    LLMBackendType,
    LLMConfig,
    LLMResponse,
    ToolDefinition,
    ToolCall,
    ToolParameter,
)
from .ollama_backend import OllamaBackend
from .openai_backend import OpenAIBackend
from .model_config import ModelConfig, get_model_config

__all__ = [
    "LLMBackend",
    "LLMBackendType",
    "LLMConfig",
    "LLMResponse",
    "ToolDefinition",
    "ToolCall",
    "ToolParameter",
    "OllamaBackend",
    "OpenAIBackend",
    "ModelConfig",
    "get_model_config",
]
