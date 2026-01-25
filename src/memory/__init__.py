"""Memory management system for the AI coding agent."""

from .models import (
    MemoryType,
    MessageRole,
    Message,
    MemoryEntry,
    ConversationTurn,
    CodeContext,
    TaskContext,
)
from .working_memory import WorkingMemory
from .episodic_memory import EpisodicMemory
from .semantic_memory import SemanticMemory
from .memory_manager import MemoryManager
from .observation_store import (
    ObservationStore,
    Observation,
    ObservationPointer,
    Importance,
    classify_importance,
)
from .context_injector import ContextInjector
from .compaction import PrioritizedSummarizer, SummarySection

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
    "SemanticMemory",
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
