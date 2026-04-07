"""Memory management system for the AI coding agent."""

from .compaction import PrioritizedSummarizer, SummarySection
from .context_injector import ContextInjector
from .memory_manager import MemoryManager
from .models import (
    CodeContext,
    ConversationTurn,
    MemoryEntry,
    MemoryType,
    Message,
    MessageRole,
    TaskContext,
)
from .working_memory import WorkingMemory

__all__ = [
    # Data models
    "MemoryType",
    "MessageRole",
    "Message",
    "MemoryEntry",
    "ConversationTurn",
    "CodeContext",
    "TaskContext",
    # Memory components
    "WorkingMemory",
    "MemoryManager",
    # Context injection and compaction
    "ContextInjector",
    "PrioritizedSummarizer",
    "SummarySection",
]
