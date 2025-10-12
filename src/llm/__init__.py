"""LLM backend integrations for the AI coding agent."""

from .base import LLMBackend, LLMBackendType, LLMConfig, LLMResponse
from .ollama_backend import OllamaBackend
from .model_config import ModelConfig, get_model_config

__all__ = [
    "LLMBackend",
    "LLMBackendType",
    "LLMConfig",
    "LLMResponse",
    "OllamaBackend",
    "ModelConfig",
    "get_model_config",
]
