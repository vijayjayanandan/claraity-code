"""Streaming Pipeline - Single canonical parser for LLM deltas.

This package owns all structural parsing decisions:
- Code fence detection (``` blocks)
- Tool call JSON assembly
- Thinking block boundaries
- Message finalization

The StreamingPipeline converts raw ProviderDelta objects into fully-parsed
Message objects with segments that the TUI can render directly.

Architecture:
    Provider -> ProviderDelta -> StreamingPipeline -> Message (with segments)
                                                          |
                                                          v
                                                    MemoryManager -> MessageStore
"""

from .pipeline import StreamingPipeline
from .state import StreamingState

__all__ = ["StreamingPipeline", "StreamingState"]
