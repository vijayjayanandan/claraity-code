"""Data models for memory system."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class MemoryType(str, Enum):
    """Types of memory storage."""

    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"


class MessageRole(str, Enum):
    """Role of a message in conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Message(BaseModel):
    """A single message in conversation."""

    role: MessageRole
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    token_count: Optional[int] = None

    def __str__(self) -> str:
        """String representation of message."""
        return f"[{self.role.value}] {self.content[:100]}..."


class MemoryEntry(BaseModel):
    """A single entry in memory."""

    id: str
    content: str
    memory_type: MemoryType
    timestamp: datetime = Field(default_factory=datetime.now)
    importance_score: float = 0.5  # 0.0 to 1.0
    access_count: int = 0
    last_accessed: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    token_count: Optional[int] = None
    embedding: Optional[List[float]] = None

    def update_access(self) -> None:
        """Update access statistics."""
        self.access_count += 1
        self.last_accessed = datetime.now()

    def calculate_relevance(self, recency_weight: float = 0.3) -> float:
        """
        Calculate relevance score based on importance, recency, and access frequency.

        Args:
            recency_weight: Weight for recency in relevance calculation

        Returns:
            Relevance score between 0.0 and 1.0
        """
        # Recency score (0-1)
        if self.last_accessed:
            hours_since_access = (datetime.now() - self.last_accessed).total_seconds() / 3600
            recency_score = 1.0 / (1.0 + hours_since_access / 24)  # Decay over days
        else:
            recency_score = 0.5

        # Frequency score (normalized)
        frequency_score = min(1.0, self.access_count / 10.0)

        # Combined relevance
        relevance = (
            self.importance_score * (1 - recency_weight)
            + recency_score * recency_weight
            + frequency_score * 0.2
        )

        return min(1.0, relevance)


class ConversationTurn(BaseModel):
    """A complete turn in conversation (user message + assistant response)."""

    id: str
    user_message: Message
    assistant_message: Message
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.now)
    summary: Optional[str] = None
    token_count: Optional[int] = None

    def compress(self) -> str:
        """Create compressed representation of the turn."""
        if self.summary:
            return self.summary

        user_preview = self.user_message.content[:100]
        assistant_preview = self.assistant_message.content[:100]
        tool_summary = f" [{len(self.tool_calls)} tools]" if self.tool_calls else ""

        return f"U: {user_preview}... | A: {assistant_preview}...{tool_summary}"


class CodeContext(BaseModel):
    """Context about code being worked on."""

    file_path: str
    content: Optional[str] = None
    language: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    summary: Optional[str] = None
    functions: List[str] = Field(default_factory=list)
    classes: List[str] = Field(default_factory=list)
    imports: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TaskContext(BaseModel):
    """Context about current task."""

    task_id: str
    description: str
    task_type: str  # e.g., "refactor", "debug", "implement", "explain"
    status: str = "in_progress"  # in_progress, completed, failed
    related_files: List[str] = Field(default_factory=list)
    key_concepts: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
