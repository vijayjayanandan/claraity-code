"""
Checkpoint Management Module

Provides checkpoint/resume functionality for the coding agent,
enabling multi-session workflows and crash recovery.
"""

from .manager import CheckpointManager, ExecutionCheckpoint, CheckpointMetadata

__all__ = [
    "CheckpointManager",
    "ExecutionCheckpoint",
    "CheckpointMetadata",
]
