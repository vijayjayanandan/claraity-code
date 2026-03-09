"""
Checkpoint Management Module

Provides checkpoint/resume functionality for the coding agent,
enabling multi-session workflows and crash recovery.
"""

from .manager import CheckpointManager, CheckpointMetadata, ExecutionCheckpoint

__all__ = [
    "CheckpointManager",
    "ExecutionCheckpoint",
    "CheckpointMetadata",
]
