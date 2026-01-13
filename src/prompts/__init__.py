"""Prompt engineering framework for optimal LLM performance."""

from .templates import PromptTemplate, PromptLibrary, TaskType
from .enhanced_prompts import EnhancedSystemPrompts, SystemPrompts, PromptSection
from .optimizer import PromptOptimizer
from .system_prompts import get_system_prompt

__all__ = [
    "PromptTemplate",
    "PromptLibrary",
    "TaskType",
    "SystemPrompts",
    "EnhancedSystemPrompts",
    "PromptSection",
    "PromptOptimizer",
    "get_system_prompt",  # New gold-standard prompts
]
