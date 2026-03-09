"""Session message store with indexes and projections.

The MessageStore is a PROJECTION of the JSONL ledger:
- Collapsed: one message per stream_id (latest wins)
- Indexed: tool_call_id -> result, fast lookups
- Filtered: mainline only, post-compaction
- Ordered by seq (line number), not timestamp

Key invariants:
- Seq uniqueness (SeqCollisionError on collision)
- Store owns seq authority via next_seq()
- Index cleanup removes from all indexes including _sidechains

v2.1: Collapse by stream_id (not provider_message_id).
"""

# Re-export Message from models for convenience
from ..models.message import Message
from .memory_store import (
    MessageStore,
    SeqCollisionError,
    StoreEvent,
    StoreNotification,
    Subscriber,
)

__all__ = [
    "MessageStore",
    "StoreEvent",
    "StoreNotification",
    "SeqCollisionError",
    "Subscriber",
    "Message",
]
