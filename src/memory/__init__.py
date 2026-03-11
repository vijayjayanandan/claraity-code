"""Memory management system for the AI coding agent."""

from .compaction import PrioritizedSummarizer, SummarySection
from .context_injector import ContextInjector
from .episodic_memory import EpisodicMemory
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
from .observation_store import (
    Importance,
    Observation,
    ObservationPointer,
    ObservationStore,
    classify_importance,
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
    "EpisodicMemory",
    "MemoryManager",
    # Observation store (Phase 2)
    "ObservationStore",
    "Observation",
    "ObservationPointer",
    "Importance",
    "classify_importance",
    # Context injection and compaction
    "ContextInjector",
    "PrioritizedSummarizer",
    "SummarySection",
]
