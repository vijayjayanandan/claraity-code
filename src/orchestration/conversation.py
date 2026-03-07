"""
Conversation Session Management

Manages a single conversation between Testing Claude and AI Coding Agent,
maintaining state across multiple turns.
"""

from pathlib import Path
from datetime import datetime
from typing import List, Optional, Any
import json

from .models import AgentMessage, AgentResponse, ConversationLog
from src.core.agent import CodingAgent
from src.execution.checkpoint.manager import CheckpointMetadata


class ConversationSession:
    """
    Manages a single conversation with AI Coding Agent.

    Maintains conversation history, handles message passing,
    and provides logging capabilities.

    Phase 1: Single-turn conversations with basic logging
    Phase 2+: Multi-turn with context preservation
    """

    def __init__(
        self,
        conversation_id: str,
        working_directory: Path,
        agent: CodingAgent,
        log_file: Optional[Path] = None,
        controller: Optional[Any] = None
    ):
        """
        Initialize conversation session.

        Args:
            conversation_id: Unique identifier for this conversation
            working_directory: Directory where agent will work
            agent: CodingAgent instance to communicate with
            log_file: Optional path to save conversation log
            controller: Optional LongRunningController for checkpoint management
        """
        self.conversation_id = conversation_id
        self.working_directory = Path(working_directory)
        self.agent = agent
        self.log_file = Path(log_file) if log_file else None
        self.controller = controller
        self.messages: List[AgentMessage] = []
        self.started_at = datetime.now()

        # Ensure working directory exists
        self.working_directory.mkdir(parents=True, exist_ok=True)

    def send_message(self, content: str) -> AgentResponse:
        """
        Send message to agent and get response.

        This is the core communication method. It:
        1. Adds user message to history
        2. Sends message to agent
        3. Extracts response and files generated
        4. Adds agent response to history
        5. Auto-saves log (if configured)

        Args:
            content: Natural language message to send to agent

        Returns:
            AgentResponse with agent's reply and metadata
        """
        # Add user message to history
        user_message = AgentMessage(
            role="user",
            content=content,
            timestamp=datetime.now()
        )
        self.messages.append(user_message)

        # Send to agent and capture response
        try:
            # NOTE: The sync execute_task() API was removed in the CLI-mode
            # consolidation.  This module needs an async rewrite to use
            # agent.stream_response() before it can work again.
            raise NotImplementedError(
                "ConversationSession.send_message() requires async rewrite. "
                "The sync execute_task() API has been removed. "
                "Use agent.stream_response() (async) instead."
            )

            # Extract files generated from tool execution history
            files_generated = self._extract_files_from_history()

            # Extract tool calls from history
            tool_calls = self._extract_tool_calls()

            # Create successful response
            # Extract content from AgentResponse object
            response_content = agent_response_obj.content if agent_response_obj else ""

            response = AgentResponse(
                content=response_content,
                files_generated=files_generated,
                tool_calls=tool_calls,
                success=True,
                error=None
            )

        except Exception as e:
            # Handle agent execution failure
            response = AgentResponse(
                content=f"Agent execution failed: {str(e)}",
                files_generated=[],
                tool_calls=[],
                success=False,
                error=f"{type(e).__name__}: {str(e)}"
            )

        # Add assistant message to history
        assistant_message = AgentMessage(
            role="assistant",
            content=response.content,
            timestamp=datetime.now(),
            metadata={
                "files_generated": response.files_generated,
                "tool_calls_count": len(response.tool_calls),
                "success": response.success
            }
        )
        self.messages.append(assistant_message)

        # Auto-save log if configured
        if self.log_file:
            self.save_log()

        return response

    def _extract_files_from_history(self) -> List[str]:
        """
        Extract files created/modified from agent's tool execution history.

        Looks for write_file and edit_file tool calls that succeeded.

        Returns:
            List of file paths that were created or modified
        """
        files = []

        # Check if agent has tool execution history
        if not hasattr(self.agent, 'tool_execution_history'):
            return files

        # Parse tool execution history
        for call in self.agent.tool_execution_history:
            # Look for file write/edit operations
            if call.get("tool") in ["write_file", "edit_file"] and call.get("success"):
                file_path = call.get("arguments", {}).get("file_path")
                if file_path:
                    files.append(file_path)

        # Deduplicate while preserving order
        seen = set()
        unique_files = []
        for f in files:
            if f not in seen:
                seen.add(f)
                unique_files.append(f)

        return unique_files

    def _extract_tool_calls(self) -> List[dict]:
        """
        Extract all tool calls from agent's execution history.

        Returns:
            List of tool call dictionaries with tool name, arguments, and success status
        """
        if not hasattr(self.agent, 'tool_execution_history'):
            return []

        # Return copy of tool execution history
        return [dict(call) for call in self.agent.tool_execution_history]

    def get_history(self) -> List[AgentMessage]:
        """
        Get conversation history.

        Returns:
            List of all messages in chronological order
        """
        return self.messages.copy()

    def save_log(self, custom_path: Optional[Path] = None) -> Path:
        """
        Save conversation to JSON file.

        Args:
            custom_path: Optional custom path to save to (overrides self.log_file)

        Returns:
            Path where log was saved
        """
        log_path = Path(custom_path) if custom_path else self.log_file

        if not log_path:
            # Generate default path in working directory
            log_path = self.working_directory / f"conversation_{self.conversation_id}.json"

        # Create conversation log
        log = self.get_log()

        # Save to JSON file
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write(log.to_json(pretty=True))

        return log_path

    def get_log(self) -> ConversationLog:
        """
        Get conversation log object.

        Returns:
            ConversationLog with current conversation state
        """
        return ConversationLog(
            conversation_id=self.conversation_id,
            messages=self.messages.copy(),
            started_at=self.started_at,
            ended_at=None,  # Not ended yet
            total_turns=len([m for m in self.messages if m.role == "user"]),
            metadata={
                "working_directory": str(self.working_directory),
                "log_file": str(self.log_file) if self.log_file else None,
                "agent_model": getattr(self.agent, 'model_name', 'unknown')
            }
        )

    # Checkpoint API Methods

    def save_checkpoint(
        self,
        description: str,
        phase: Optional[str] = None,
        pending_tasks: Optional[List[str]] = None
    ) -> str:
        """
        Save checkpoint programmatically (API method).

        Provides programmatic access to checkpoint creation for tests and
        automation, without requiring CLI commands.

        Args:
            description: What was accomplished in this session
            phase: Optional current development phase (e.g., 'Phase 1')
            pending_tasks: Optional list of tasks remaining to complete

        Returns:
            checkpoint_id: ID of created checkpoint

        Raises:
            RuntimeError: If controller not initialized
        """
        if not self.controller:
            raise RuntimeError(
                "Controller not initialized. Cannot create checkpoint. "
                "Pass controller parameter when creating ConversationSession."
            )

        checkpoint_id = self.controller.create_checkpoint(
            description=description,
            current_phase=phase,
            pending_tasks=pending_tasks
        )

        if not checkpoint_id:
            raise RuntimeError("Failed to create checkpoint (controller returned None)")

        return checkpoint_id

    def list_checkpoints(self) -> List[CheckpointMetadata]:
        """
        List all checkpoints for this session (API method).

        Returns:
            List of CheckpointMetadata objects (newest first)

        Raises:
            RuntimeError: If controller not initialized
        """
        if not self.controller:
            raise RuntimeError(
                "Controller not initialized. Cannot list checkpoints. "
                "Pass controller parameter when creating ConversationSession."
            )

        return self.controller.list_checkpoints()

    def restore_checkpoint(self, checkpoint_id: str) -> bool:
        """
        Restore from a checkpoint (API method).

        This restores both:
        - Agent's internal state (working memory, tool history)
        - ConversationSession's message history

        Args:
            checkpoint_id: ID of checkpoint to restore

        Returns:
            True if restoration successful, False otherwise

        Raises:
            RuntimeError: If controller not initialized
        """
        if not self.controller:
            raise RuntimeError(
                "Controller not initialized. Cannot restore checkpoint. "
                "Pass controller parameter when creating ConversationSession."
            )

        # Restore agent state via controller
        success = self.controller.restore_checkpoint(checkpoint_id)

        if not success:
            return False

        # Also restore ConversationSession's message history
        try:
            # Load checkpoint to get working_memory
            checkpoint = self.controller.checkpoint_manager.load_checkpoint(checkpoint_id)

            # Clear current messages
            self.messages.clear()

            # Convert checkpoint working_memory to AgentMessage objects
            for msg_dict in checkpoint.working_memory:
                timestamp_str = msg_dict.get("timestamp")
                timestamp = datetime.fromisoformat(timestamp_str) if timestamp_str else datetime.now()

                message = AgentMessage(
                    role=msg_dict["role"],
                    content=msg_dict["content"],
                    timestamp=timestamp,
                    metadata=msg_dict.get("metadata", {})
                )
                self.messages.append(message)

            return True

        except Exception as e:
            # If session restore fails, we've already restored agent
            # Log the error but still return True since agent was restored
            print(f"[WARN] Failed to restore session history: {e}")
            print(f"[INFO] Agent state was restored successfully")
            return True

    def clear_checkpoints(self) -> int:
        """
        Delete all checkpoints for this session (API method).

        WARNING: This operation is irreversible!

        Returns:
            Number of checkpoints deleted

        Raises:
            RuntimeError: If controller not initialized
        """
        if not self.controller:
            raise RuntimeError(
                "Controller not initialized. Cannot clear checkpoints. "
                "Pass controller parameter when creating ConversationSession."
            )

        return self.controller.clear_all_checkpoints()
