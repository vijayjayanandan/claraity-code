"""
Data models for agent-to-agent orchestration.

Defines the communication protocol between Claude Code (testing agent)
and AI Coding Agent (subject under test).
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class AgentMessage:
    """
    Single message in a conversation.

    Represents one turn in the conversation, either from the user
    (Testing Claude) or the assistant (AI Coding Agent).
    """
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentMessage":
        """Create from dictionary"""
        return cls(
            role=data["role"],
            content=data["content"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            metadata=data.get("metadata", {})
        )


@dataclass
class AgentResponse:
    """
    Response from AI Coding Agent.

    Contains the agent's natural language response plus metadata about
    what actions it took (files generated, tools called, etc.).
    """
    content: str  # Natural language response
    files_generated: list[str] = field(default_factory=list)  # Files created/modified
    tool_calls: list[dict[str, Any]] = field(default_factory=list)  # Tools executed
    success: bool = True
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "content": self.content,
            "files_generated": self.files_generated,
            "tool_calls": self.tool_calls,
            "success": self.success,
            "error": self.error,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentResponse":
        """Create from dictionary"""
        return cls(
            content=data["content"],
            files_generated=data.get("files_generated", []),
            tool_calls=data.get("tool_calls", []),
            success=data.get("success", True),
            error=data.get("error"),
            metadata=data.get("metadata", {})
        )


@dataclass
class ConversationLog:
    """
    Complete conversation history.

    Records the full conversation between Testing Claude and AI Coding Agent,
    including all messages, timing, and metadata.
    """
    conversation_id: str
    messages: list[AgentMessage]
    started_at: datetime
    ended_at: datetime | None = None
    total_turns: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "conversation_id": self.conversation_id,
            "messages": [msg.to_dict() for msg in self.messages],
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "total_turns": self.total_turns,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConversationLog":
        """Create from dictionary"""
        return cls(
            conversation_id=data["conversation_id"],
            messages=[AgentMessage.from_dict(msg) for msg in data["messages"]],
            started_at=datetime.fromisoformat(data["started_at"]),
            ended_at=datetime.fromisoformat(data["ended_at"]) if data.get("ended_at") else None,
            total_turns=data.get("total_turns", 0),
            metadata=data.get("metadata", {})
        )

    def to_json(self, pretty: bool = True) -> str:
        """Convert to JSON string"""
        indent = 2 if pretty else None
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, json_str: str) -> "ConversationLog":
        """Create from JSON string"""
        data = json.loads(json_str)
        return cls.from_dict(data)
