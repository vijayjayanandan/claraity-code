"""
Agent Orchestrator

High-level API for managing conversations between Claude Code (testing agent)
and AI Coding Agent (subject under test).
"""

import os
import uuid
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

from .conversation import ConversationSession
from .models import AgentResponse, ConversationLog
from src.core.agent import CodingAgent
from src.execution.controller import LongRunningController


class AgentOrchestrator:
    """
    Orchestrates communication between Claude Code and AI Coding Agent.

    Provides a clean API for:
    - Starting conversations
    - Sending messages
    - Managing multiple concurrent sessions
    - Logging conversations

    Phase 1: Basic communication (single messages)
    Phase 2+: Multi-turn conversations with scenarios
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        backend: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        output_dir: str = "./orchestration-logs",
        working_directory: str = "./orchestration-workspace"
    ):
        """
        Initialize orchestrator.

        Args:
            model_name: LLM model to use for agent (from .env: LLM_MODEL)
            backend: Backend type (from .env: LLM_BACKEND)
            base_url: API base URL (from .env: LLM_HOST)
            api_key: API key (from .env: OPENAI_API_KEY)
            output_dir: Directory for conversation logs
            working_directory: Root directory for agent workspaces
        """
        # Read from .env if not provided
        self.model_name = model_name or os.environ.get("LLM_MODEL")
        self.backend = backend or os.environ.get("LLM_BACKEND", "openai")
        self.base_url = base_url or os.environ.get("LLM_HOST")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.output_dir = Path(output_dir)
        self.working_directory = Path(working_directory)

        # Validate configuration
        if not self.model_name:
            raise ValueError("No model name found. Set LLM_MODEL in .env or pass model_name parameter.")
        if not self.base_url:
            raise ValueError("No base URL found. Set LLM_HOST in .env or pass base_url parameter.")
        if not self.api_key:
            raise ValueError("No API key found. Set OPENAI_API_KEY in .env or pass api_key parameter."
            )

        # Create directories
        self.output_dir.mkdir(exist_ok=True, parents=True)
        self.working_directory.mkdir(exist_ok=True, parents=True)

        # Track active sessions
        self.active_sessions: Dict[str, ConversationSession] = {}

    def start_conversation(
        self,
        task_description: Optional[str] = None,
        isolated_workspace: bool = True
    ) -> ConversationSession:
        """
        Start new conversation with agent.

        Creates a fresh CodingAgent instance and ConversationSession.
        Optionally creates an isolated workspace for this conversation.

        Args:
            task_description: Optional description of the task (metadata only)
            isolated_workspace: If True, create unique workspace subdirectory

        Returns:
            ConversationSession object for this conversation
        """
        # Generate unique conversation ID
        conversation_id = str(uuid.uuid4())[:8]

        # Determine workspace directory
        if isolated_workspace:
            workspace = self.working_directory / f"conv_{conversation_id}"
        else:
            workspace = self.working_directory

        workspace.mkdir(parents=True, exist_ok=True)

        # IMPORTANT: Convert to absolute path for agent
        # Agent needs absolute path to know where to create files
        workspace_abs = workspace.resolve()

        # Initialize CodingAgent
        agent = CodingAgent(
            model_name=self.model_name,
            backend=self.backend,
            base_url=self.base_url,
            context_window=int(os.getenv("LLM_CONTEXT_WINDOW", "32768")),
            api_key=self.api_key,
            working_directory=str(workspace_abs),  # Use absolute path
            permission_mode="auto",  # No approval prompts for testing
        )

        # Initialize Long Running Controller for checkpoints
        controller = LongRunningController(
            agent=agent,
            project_dir=str(workspace_abs),
            max_checkpoints=10
        )

        # Wire controller to checkpoint tool
        for tool in agent.tool_executor.tools.values():
            if tool.name == "create_checkpoint":
                tool.set_controller(controller)
                break

        # Create log file path
        log_file = self.output_dir / f"conversation_{conversation_id}.json"

        # Create conversation session
        session = ConversationSession(
            conversation_id=conversation_id,
            working_directory=workspace_abs,  # Use absolute path
            agent=agent,
            log_file=log_file,
            controller=controller  # Pass controller for checkpoint API
        )

        # Track session
        self.active_sessions[conversation_id] = session

        # Store metadata
        if task_description:
            session.get_log().metadata["task_description"] = task_description

        return session

    def send_message(
        self,
        message: str,
        isolated_workspace: bool = True
    ) -> AgentResponse:
        """
        Simple API: send single message, get response (no session tracking).

        Convenience method for one-off messages without managing sessions.
        Creates an ephemeral conversation that is not tracked.

        Args:
            message: Message to send to agent
            isolated_workspace: If True, create unique workspace

        Returns:
            AgentResponse from agent
        """
        # Start ephemeral conversation
        session = self.start_conversation(isolated_workspace=isolated_workspace)

        # Send message
        response = session.send_message(message)

        # Remove from active sessions (not tracked)
        del self.active_sessions[session.conversation_id]

        return response

    def get_session(self, conversation_id: str) -> Optional[ConversationSession]:
        """
        Get active session by ID.

        Args:
            conversation_id: Conversation ID to look up

        Returns:
            ConversationSession if found, None otherwise
        """
        return self.active_sessions.get(conversation_id)

    def end_conversation(self, conversation_id: str) -> ConversationLog:
        """
        End conversation and return full log.

        Saves conversation to disk, removes from active sessions,
        and returns the final conversation log.

        Args:
            conversation_id: Conversation ID to end

        Returns:
            ConversationLog with complete conversation history

        Raises:
            KeyError: If conversation ID not found
        """
        session = self.active_sessions.get(conversation_id)
        if not session:
            raise KeyError(f"Conversation {conversation_id} not found in active sessions")

        # Get conversation log
        log = session.get_log()

        # Mark as ended
        log.ended_at = datetime.now()
        log.metadata["ended_at"] = log.ended_at.isoformat()

        # Save final log
        log_path = session.save_log()
        log.metadata["log_path"] = str(log_path)

        # Remove from active sessions
        del self.active_sessions[conversation_id]

        return log

    def list_active_conversations(self) -> Dict[str, dict]:
        """
        List all active conversations.

        Returns:
            Dictionary mapping conversation IDs to basic info
        """
        return {
            conv_id: {
                "conversation_id": conv_id,
                "started_at": session.started_at.isoformat(),
                "working_directory": str(session.working_directory),
                "message_count": len(session.messages),
                "turns": len([m for m in session.messages if m.role == "user"])
            }
            for conv_id, session in self.active_sessions.items()
        }
