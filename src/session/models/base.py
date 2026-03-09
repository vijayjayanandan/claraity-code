"""Base utilities for session models.

Note: Seq authority is owned by MessageStore, NOT a global generator.
Factory methods that need seq must accept a store parameter.
See v3.1 Patch 1 for rationale.
"""

import uuid as uuid_lib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

# =============================================================================
# Constants
# =============================================================================

SCHEMA_VERSION = 1


# =============================================================================
# Utility Functions
# =============================================================================


def generate_uuid() -> str:
    """Generate a new UUID string."""
    return str(uuid_lib.uuid4())


def now_iso() -> str:
    """Get current time as ISO 8601 string."""
    return datetime.utcnow().isoformat() + "Z"


def generate_stream_id() -> str:
    """Generate a unique stream ID for message streaming/collapse."""
    return f"stream_{uuid_lib.uuid4().hex[:12]}"


def generate_tool_call_id() -> str:
    """Generate a canonical tool call ID safe for all LLM providers.

    Format: tc_<32 hex chars> (35 chars total)
    Character set: [a-f0-9_] -- subset of every provider's allowed set.
    Satisfies: Anthropic (^[a-zA-Z0-9_-]+$), OpenAI (max 40),
               Mistral (min 9), Gemini (any non-null string).
    """
    return f"tc_{uuid_lib.uuid4().hex}"


# =============================================================================
# Session Context
# =============================================================================


@dataclass
class SessionContext:
    """Common session context fields."""

    session_id: str
    cwd: str
    git_branch: str
    version: str
    slug: str | None = None
    user_type: str = "external"

    def to_dict(self) -> dict[str, Any]:
        result = {
            "session_id": self.session_id,
            "cwd": self.cwd,
            "git_branch": self.git_branch,
            "version": self.version,
            "user_type": self.user_type,
        }
        if self.slug:
            result["slug"] = self.slug
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionContext":
        """Create SessionContext from dict."""
        return cls(
            session_id=data.get("session_id", ""),
            cwd=data.get("cwd", ""),
            git_branch=data.get("git_branch", ""),
            version=data.get("version", ""),
            slug=data.get("slug"),
            user_type=data.get("user_type", "external"),
        )
