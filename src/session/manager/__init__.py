"""Session lifecycle management.

SessionManager: High-level session lifecycle management
- create_session(): New session creation
- resume_session(): Load from JSONL file
- start_writer(): Bind writer to store (async)
- close(): Graceful shutdown

SessionInfo: Session metadata dataclass

Key design per v3.1 Patch 1:
- Store owns seq authority
- NO global reset_seq() calls
- Store starts at _max_seq=0 for new sessions
- Store._max_seq set from line numbers during replay
"""

from .session_manager import (
    SessionManager,
    SessionInfo,
)

__all__ = [
    "SessionManager",
    "SessionInfo",
]
