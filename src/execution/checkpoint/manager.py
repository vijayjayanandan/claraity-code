"""
Checkpoint Manager - Save and Restore Agent Execution State

Provides "save game" functionality for the coding agent, enabling:
- Multi-session workflows (pause and resume work)
- Crash recovery (restore after failures)
- Experiment tracking (save different approaches)

Design:
- Each checkpoint = complete snapshot of agent's "brain" at that moment
- Saved as JSON files in .checkpoints/ directory
- Auto-cleanup keeps only N most recent checkpoints
- Restore populates agent's memory and tool history

Author: AI Coding Agent Team
Phase: 1 - Self-Testing & Long-Running Execution
"""

import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


@dataclass
class CheckpointMetadata:
    """
    Metadata about a checkpoint.

    Attributes:
        checkpoint_id: Unique identifier (UUID)
        timestamp: When checkpoint was created
        task_description: What the agent was working on
        working_directory: Where the agent was working
        files_modified_count: Number of files modified
        tool_calls_count: Number of tool calls executed
        conversation_turns: Number of conversation turns
    """

    checkpoint_id: str
    timestamp: str  # ISO 8601 format
    task_description: str
    working_directory: str
    files_modified_count: int
    tool_calls_count: int
    conversation_turns: int


@dataclass
class ExecutionCheckpoint:
    """
    Complete snapshot of agent execution state.

    This is the full "save game" that contains everything needed
    to restore the agent to a specific point in time.

    Attributes:
        metadata: Checkpoint metadata
        working_memory: Recent conversation messages (last 10-20)
        episodic_memory: Compressed summaries of older conversations
        task_context: Project type, key files, key concepts
        tool_execution_history: Complete history of tool calls
        files_modified: list of files created/modified
        current_todos: Current todo list from TodoWrite tool
        current_phase: Current development phase (e.g., "Phase 1")
        pending_tasks: Tasks remaining to complete
    """

    metadata: CheckpointMetadata
    working_memory: list[dict[str, Any]]  # Recent messages
    episodic_memory: list[str]  # Compressed summaries
    task_context: dict[str, Any]  # Project context
    tool_execution_history: list[dict[str, Any]]  # All tool calls
    files_modified: list[str]  # File paths
    current_todos: list[dict[str, Any]] | None = None  # TodoWrite state
    current_phase: str | None = None
    pending_tasks: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert checkpoint to dictionary for JSON serialization."""
        return {
            "metadata": asdict(self.metadata),
            "working_memory": self.working_memory,
            "episodic_memory": self.episodic_memory,
            "task_context": self.task_context,
            "tool_execution_history": self.tool_execution_history,
            "files_modified": self.files_modified,
            "current_todos": self.current_todos,
            "current_phase": self.current_phase,
            "pending_tasks": self.pending_tasks,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionCheckpoint":
        """Restore checkpoint from dictionary (JSON deserialization)."""
        metadata = CheckpointMetadata(**data["metadata"])
        return cls(
            metadata=metadata,
            working_memory=data["working_memory"],
            episodic_memory=data["episodic_memory"],
            task_context=data["task_context"],
            tool_execution_history=data["tool_execution_history"],
            files_modified=data["files_modified"],
            current_todos=data.get("current_todos"),
            current_phase=data.get("current_phase"),
            pending_tasks=data.get("pending_tasks"),
        )


class CheckpointManager:
    """
    Manages saving and restoring agent execution state.

    Usage:
        # Save checkpoint
        manager = CheckpointManager()
        checkpoint_id = manager.save_checkpoint(
            agent=coding_agent,
            execution_progress="Implemented authentication module",
            task_description="Building user auth system"
        )

        # List checkpoints
        checkpoints = manager.list_checkpoints()

        # Load checkpoint
        checkpoint = manager.load_checkpoint(checkpoint_id)

        # Restore to agent
        manager.restore_to_agent(checkpoint, coding_agent)

    Attributes:
        checkpoint_dir: Directory where checkpoints are saved
        max_checkpoints: Maximum number of checkpoints to keep (auto-cleanup)
    """

    def __init__(self, checkpoint_dir: str = ".checkpoints", max_checkpoints: int = 10):
        """
        Initialize checkpoint manager.

        Args:
            checkpoint_dir: Directory to save checkpoints (default: .checkpoints)
            max_checkpoints: Max checkpoints to keep (default: 10)
        """
        self.checkpoint_dir = Path(checkpoint_dir)
        self.max_checkpoints = max_checkpoints

        # Create checkpoint directory if it doesn't exist
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def save_checkpoint(
        self,
        agent: Any,  # CodingAgent instance
        execution_progress: str,
        task_description: str = "Ongoing work",
        current_phase: str | None = None,
        pending_tasks: list[str] | None = None,
    ) -> str:
        """
        Save complete agent execution state to checkpoint.

        This creates a "save game" of the agent's current state, including:
        - Recent conversation history
        - Episodic memory summaries
        - Task context
        - All tool calls executed
        - Files modified

        Args:
            agent: CodingAgent instance to checkpoint
            execution_progress: Description of current progress
            task_description: What the agent is working on
            current_phase: Current development phase (e.g., "Phase 1")
            pending_tasks: list of tasks remaining

        Returns:
            checkpoint_id: Unique ID of saved checkpoint

        Raises:
            AttributeError: If agent doesn't have required memory attributes
            OSError: If checkpoint file cannot be written
        """
        # Generate unique checkpoint ID
        checkpoint_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now().isoformat()

        # Extract working memory (recent conversation)
        working_memory_messages = []
        try:
            if (
                hasattr(agent, "memory")
                and hasattr(agent.memory, "working_memory")
                and hasattr(agent.memory.working_memory, "messages")
            ):
                # Truncate to last 20 messages to keep checkpoint size manageable
                recent_messages = agent.memory.working_memory.messages[-20:]
                working_memory_messages = [
                    {
                        "role": msg.role.value if hasattr(msg.role, "value") else str(msg.role),
                        "content": msg.content,
                        "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
                    }
                    for msg in recent_messages
                ]
        except (TypeError, AttributeError):
            # Agent might not have proper memory structure
            pass

        # Extract episodic memory (compressed summaries)
        episodic_memory_summaries = []
        try:
            if hasattr(agent, "memory") and hasattr(agent.memory, "episodic_memory"):
                if hasattr(agent.memory.episodic_memory, "compressed_history"):
                    episodic_memory_summaries = (
                        agent.memory.episodic_memory.compressed_history.copy()
                    )
        except (TypeError, AttributeError):
            pass

        # Extract task context
        task_context = {}
        try:
            if hasattr(agent, "memory") and hasattr(agent.memory, "task_context"):
                ctx = agent.memory.task_context
                # Safely extract each field, ensuring it's a proper type (not Mock)
                project_type = getattr(ctx, "project_type", None)
                key_files = getattr(ctx, "key_files", [])
                key_concepts = getattr(ctx, "key_concepts", [])

                # Only include if they're JSON-serializable types
                if isinstance(project_type, str | type(None)):
                    task_context["project_type"] = project_type
                if isinstance(key_files, list):
                    task_context["key_files"] = key_files
                if isinstance(key_concepts, list):
                    task_context["key_concepts"] = key_concepts
        except (TypeError, AttributeError):
            pass

        # Extract tool execution history
        tool_execution_history = []
        try:
            if hasattr(agent, "tool_execution_history"):
                tool_execution_history = [dict(call) for call in agent.tool_execution_history]
        except (TypeError, AttributeError):
            pass

        # Extract files modified (from tool history)
        files_modified = []
        for tool_call in tool_execution_history:
            if tool_call.get("tool") in ["write_file", "edit_file", "append_to_file"]:
                if tool_call.get("success"):
                    file_path = tool_call.get("arguments", {}).get("file_path")
                    if file_path and file_path not in files_modified:
                        files_modified.append(file_path)

        # Extract current todos (from TodoWrite tool state)
        current_todos_list = None
        try:
            if hasattr(agent, "current_todos") and agent.current_todos is not None:
                # Agent has todos stored directly
                current_todos_list = agent.current_todos.copy()
            else:
                # Try to extract from tool execution history (last TodoWrite call)
                for tool_call in reversed(tool_execution_history):
                    if tool_call.get("tool") == "todo_write":
                        if tool_call.get("success") and "arguments" in tool_call:
                            todos_arg = tool_call["arguments"].get("todos")
                            if todos_arg:
                                current_todos_list = todos_arg
                                break
        except (TypeError, AttributeError):
            pass

        # Get working directory
        working_directory = getattr(agent, "working_directory", os.getcwd())

        # Create metadata
        metadata = CheckpointMetadata(
            checkpoint_id=checkpoint_id,
            timestamp=timestamp,
            task_description=task_description,
            working_directory=str(working_directory),
            files_modified_count=len(files_modified),
            tool_calls_count=len(tool_execution_history),
            conversation_turns=len([m for m in working_memory_messages if m["role"] == "user"]),
        )

        # Create checkpoint
        checkpoint = ExecutionCheckpoint(
            metadata=metadata,
            working_memory=working_memory_messages,
            episodic_memory=episodic_memory_summaries,
            task_context=task_context,
            tool_execution_history=tool_execution_history,
            files_modified=files_modified,
            current_todos=current_todos_list,
            current_phase=current_phase,
            pending_tasks=pending_tasks,
        )

        # Save to file
        checkpoint_file = self.checkpoint_dir / f"checkpoint_{checkpoint_id}.json"
        with open(checkpoint_file, "w", encoding="utf-8") as f:
            json.dump(checkpoint.to_dict(), f, indent=2, ensure_ascii=False)

        # Cleanup old checkpoints
        self._cleanup_old_checkpoints()

        return checkpoint_id

    def load_checkpoint(self, checkpoint_id: str) -> ExecutionCheckpoint:
        """
        Load checkpoint from disk.

        Args:
            checkpoint_id: ID of checkpoint to load

        Returns:
            ExecutionCheckpoint object

        Raises:
            FileNotFoundError: If checkpoint file doesn't exist
            json.JSONDecodeError: If checkpoint file is corrupted
        """
        if not self._is_valid_checkpoint_id(checkpoint_id):
            raise ValueError(f"Invalid checkpoint ID: {checkpoint_id}")

        checkpoint_file = self.checkpoint_dir / f"checkpoint_{checkpoint_id}.json"

        if not checkpoint_file.exists():
            raise FileNotFoundError(f"Checkpoint {checkpoint_id} not found at {checkpoint_file}")

        with open(checkpoint_file, encoding="utf-8") as f:
            data = json.load(f)

        return ExecutionCheckpoint.from_dict(data)

    def restore_to_agent(self, checkpoint: ExecutionCheckpoint, agent: Any) -> None:
        """
        Restore checkpoint state to agent.

        This "loads the save game" by populating the agent's memory
        and tool history from the checkpoint.

        NOTE: This modifies the agent in-place. The agent's previous state
        will be lost unless you saved it to another checkpoint first.

        Args:
            checkpoint: Checkpoint to restore from
            agent: CodingAgent instance to restore to

        Raises:
            AttributeError: If agent doesn't have required memory attributes
        """
        # Restore working memory
        if hasattr(agent, "memory") and hasattr(agent.memory, "working_memory"):
            # Clear existing messages
            agent.memory.working_memory.messages.clear()

            # Restore messages from checkpoint
            from src.memory.memory_manager import Message, MessageRole

            for msg_dict in checkpoint.working_memory:
                role = MessageRole(msg_dict["role"])
                timestamp_str = msg_dict.get("timestamp")
                timestamp = datetime.fromisoformat(timestamp_str) if timestamp_str else None

                message = Message(role=role, content=msg_dict["content"], timestamp=timestamp)
                agent.memory.working_memory.messages.append(message)

        # Restore episodic memory
        if hasattr(agent, "memory") and hasattr(agent.memory, "episodic_memory"):
            if hasattr(agent.memory.episodic_memory, "compressed_history"):
                agent.memory.episodic_memory.compressed_history = checkpoint.episodic_memory.copy()

        # Restore task context
        if hasattr(agent, "memory") and hasattr(agent.memory, "task_context"):
            ctx = agent.memory.task_context
            ctx.project_type = checkpoint.task_context.get("project_type")
            ctx.key_files = checkpoint.task_context.get("key_files", [])
            ctx.key_concepts = checkpoint.task_context.get("key_concepts", [])

        # Restore tool execution history
        if hasattr(agent, "tool_execution_history"):
            agent.tool_execution_history = [
                dict(call) for call in checkpoint.tool_execution_history
            ]

    def list_checkpoints(self) -> list[CheckpointMetadata]:
        """
        list all available checkpoints, sorted by timestamp (newest first).

        Returns:
            list of CheckpointMetadata objects
        """
        checkpoints = []

        # Find all checkpoint files
        checkpoint_files = list(self.checkpoint_dir.glob("checkpoint_*.json"))

        for checkpoint_file in checkpoint_files:
            try:
                with open(checkpoint_file, encoding="utf-8") as f:
                    data = json.load(f)

                metadata = CheckpointMetadata(**data["metadata"])
                checkpoints.append(metadata)
            except (json.JSONDecodeError, KeyError, TypeError):
                # Skip corrupted checkpoint files
                continue

        # Sort by timestamp (newest first)
        checkpoints.sort(key=lambda c: c.timestamp, reverse=True)

        return checkpoints

    def _is_valid_checkpoint_id(self, checkpoint_id: str) -> bool:
        """
        Validate checkpoint ID to prevent path traversal attacks.

        Args:
            checkpoint_id: Checkpoint ID to validate

        Returns:
            True if checkpoint_id is safe (8-char hex), False otherwise
        """
        import re

        return bool(re.match(r"^[a-f0-9]{8}$", checkpoint_id))

    def _cleanup_old_checkpoints(self) -> None:
        """
        Delete old checkpoints to stay within max_checkpoints limit.

        Keeps only the N most recent checkpoints, where N = max_checkpoints.
        Includes path traversal protection.
        """
        checkpoints = self.list_checkpoints()

        # If we're within the limit, no cleanup needed
        if len(checkpoints) <= self.max_checkpoints:
            return

        # Delete oldest checkpoints (beyond max_checkpoints)
        checkpoints_to_delete = checkpoints[self.max_checkpoints :]

        for checkpoint_meta in checkpoints_to_delete:
            # Security: Validate checkpoint ID before using it
            if not self._is_valid_checkpoint_id(checkpoint_meta.checkpoint_id):
                continue

            checkpoint_file = (
                self.checkpoint_dir / f"checkpoint_{checkpoint_meta.checkpoint_id}.json"
            )

            # Security: Verify file is inside checkpoint directory
            try:
                resolved_path = checkpoint_file.resolve()
                checkpoint_dir_resolved = self.checkpoint_dir.resolve()

                if not resolved_path.is_relative_to(checkpoint_dir_resolved):
                    continue

                checkpoint_file.unlink()
            except (OSError, ValueError):
                # Skip if file can't be deleted (e.g., permission issue)
                continue
