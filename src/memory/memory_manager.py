"""Memory Manager - Orchestrates all memory layers."""

from typing import List, Optional, Dict, Any, Tuple
from pathlib import Path
from datetime import datetime
import uuid

from .working_memory import WorkingMemory
from .episodic_memory import EpisodicMemory
from .semantic_memory import SemanticMemory
from .file_loader import MemoryFileLoader
from .models import (
    Message,
    MessageRole,
    ConversationTurn,
    CodeContext,
    TaskContext,
    MemoryType,
)


class MemoryManager:
    """
    Central memory manager that orchestrates all memory layers.
    Handles dynamic token allocation, cross-layer retrieval, and memory persistence.
    """

    def __init__(
        self,
        total_context_tokens: int = 4096,
        working_memory_tokens: int = 2000,
        episodic_memory_tokens: int = 1000,
        system_prompt_tokens: int = 300,
        embedding_model: str = "text-embedding-v4",  # Alibaba Cloud API
        persist_directory: str = "./data",
        load_file_memories: bool = True,
        starting_directory: Optional[Path] = None,
    ):
        """
        Initialize memory manager.

        Args:
            total_context_tokens: Total available context window
            working_memory_tokens: Tokens allocated to working memory
            episodic_memory_tokens: Tokens allocated to episodic memory
            system_prompt_tokens: Tokens reserved for system prompt
            embedding_model: Embedding model for semantic memory
            persist_directory: Directory for persistence
            load_file_memories: Whether to load hierarchical file memories on init
            starting_directory: Starting directory for file memory search (default: cwd)
        """
        self.total_context_tokens = total_context_tokens
        self.system_prompt_tokens = system_prompt_tokens

        # Initialize memory layers
        self.working_memory = WorkingMemory(max_tokens=working_memory_tokens)

        self.episodic_memory = EpisodicMemory(
            max_tokens=episodic_memory_tokens,
            compression_threshold=0.8,
        )

        self.semantic_memory = SemanticMemory(
            persist_directory=f"{persist_directory}/embeddings",
            embedding_model=embedding_model,
        )

        # Initialize file-based memory loader
        self.file_loader = MemoryFileLoader()
        self.file_memory_content = ""

        # Load file memories if requested
        if load_file_memories:
            self.load_file_memories(starting_directory)

        # Session metadata
        self.session_id = str(uuid.uuid4())
        self.session_start = datetime.now()
        self.persist_directory = Path(persist_directory)

    def add_user_message(
        self, content: str, metadata: Optional[Dict] = None
    ) -> None:
        """
        Add user message to working memory.

        Args:
            content: Message content
            metadata: Optional metadata
        """
        self.working_memory.add_message(
            role=MessageRole.USER,
            content=content,
            metadata=metadata,
        )

    def add_assistant_message(
        self,
        content: str,
        tool_calls: Optional[List[Dict]] = None,
        metadata: Optional[Dict] = None,
    ) -> None:
        """
        Add assistant message and create conversation turn.

        Args:
            content: Message content
            tool_calls: Optional tool calls made
            metadata: Optional metadata
        """
        self.working_memory.add_message(
            role=MessageRole.ASSISTANT,
            content=content,
            metadata=metadata,
        )

        # Create conversation turn for episodic memory
        if len(self.working_memory.messages) >= 2:
            messages = self.working_memory.messages
            # Find last user message
            user_msg = None
            for msg in reversed(messages):
                if msg.role == MessageRole.USER:
                    user_msg = msg
                    break

            if user_msg:
                assistant_msg = messages[-1]  # Last message is assistant

                turn = ConversationTurn(
                    id=str(uuid.uuid4()),
                    user_message=user_msg,
                    assistant_message=assistant_msg,
                    tool_calls=tool_calls or [],
                    timestamp=datetime.now(),
                )

                self.episodic_memory.add_turn(turn)

    def add_code_context(self, code_context: CodeContext) -> None:
        """
        Add code context to both working and semantic memory.

        Args:
            code_context: CodeContext to add
        """
        # Add to working memory
        self.working_memory.add_code_context(code_context)

        # Also store in semantic memory for long-term retrieval
        self.semantic_memory.add_code_context(code_context, importance_score=0.6)

    def set_task_context(self, task_context: TaskContext) -> None:
        """
        Set current task context.

        Args:
            task_context: TaskContext to set
        """
        self.working_memory.set_task_context(task_context)

    def retrieve_relevant_context(
        self, query: str, n_results: int = 5
    ) -> List[Tuple[str, float, Dict[str, Any]]]:
        """
        Retrieve relevant context from semantic memory.

        Args:
            query: Search query
            n_results: Number of results

        Returns:
            List of (content, similarity, metadata) tuples
        """
        return self.semantic_memory.search(query=query, n_results=n_results)

    def retrieve_similar_code(
        self, query: str, language: Optional[str] = None, n_results: int = 3
    ) -> List[Tuple[str, float, Dict[str, Any]]]:
        """
        Retrieve similar code from semantic memory.

        Args:
            query: Search query
            language: Optional language filter
            n_results: Number of results

        Returns:
            List of matching code contexts
        """
        return self.semantic_memory.search_code(
            query=query, language=language, n_results=n_results
        )

    def get_context_for_llm(
        self,
        system_prompt: str,
        include_episodic: bool = True,
        include_semantic_query: Optional[str] = None,
        include_file_memories: bool = True,
    ) -> List[Dict[str, str]]:
        """
        Build complete context for LLM from all memory layers.

        Args:
            system_prompt: System prompt to include
            include_episodic: Whether to include episodic memory summary
            include_semantic_query: Optional query to retrieve from semantic memory
            include_file_memories: Whether to include file-based memories (default: True)

        Returns:
            List of message dictionaries for LLM
        """
        context = []

        # 1. System prompt
        context.append({"role": "system", "content": system_prompt})

        # 2. File-based memories (project, user, enterprise)
        if include_file_memories and self.file_memory_content:
            context.append(
                {
                    "role": "system",
                    "content": f"Project and user memory context:\n{self.file_memory_content}",
                }
            )

        # 3. Episodic memory summary (if requested)
        if include_episodic and self.episodic_memory.conversation_turns:
            episodic_summary = self.episodic_memory.get_context_summary()
            if episodic_summary:
                context.append(
                    {
                        "role": "system",
                        "content": f"Previous conversation context:\n{episodic_summary}",
                    }
                )

        # 4. Semantic memory retrieval (if query provided)
        if include_semantic_query:
            semantic_results = self.retrieve_relevant_context(
                include_semantic_query, n_results=3
            )
            if semantic_results:
                relevant_info = "\n\n".join(
                    [f"- {content} (relevance: {score:.2f})" for content, score, _ in semantic_results]
                )
                context.append(
                    {
                        "role": "system",
                        "content": f"Relevant context from knowledge base:\n{relevant_info}",
                    }
                )

        # 5. Working memory (current conversation)
        working_context = self.working_memory.get_context_for_llm()
        context.extend(working_context)

        return context

    def get_token_budget(self) -> Dict[str, int]:
        """
        Get current token allocation across memory layers.

        Returns:
            Dictionary with token counts
        """
        working_tokens = self.working_memory.get_current_token_count()
        episodic_tokens = self.episodic_memory.current_token_count

        return {
            "total_available": self.total_context_tokens,
            "system_prompt_reserved": self.system_prompt_tokens,
            "working_memory": working_tokens,
            "episodic_memory": episodic_tokens,
            "remaining": self.total_context_tokens
            - self.system_prompt_tokens
            - working_tokens
            - episodic_tokens,
        }

    def store_solution(
        self, problem: str, solution: str, metadata: Optional[Dict] = None
    ) -> str:
        """
        Store a problem-solution pair in semantic memory.

        Args:
            problem: Problem description
            solution: Solution
            metadata: Optional metadata

        Returns:
            ID of stored solution
        """
        return self.semantic_memory.add_solution(
            problem=problem, solution=solution, metadata=metadata
        )

    def search_history(
        self, query: str, max_results: int = 3
    ) -> List[ConversationTurn]:
        """
        Search conversation history.

        Args:
            query: Search query
            max_results: Maximum results

        Returns:
            List of relevant conversation turns
        """
        return self.episodic_memory.search_history(query=query, max_results=max_results)

    def save_session(
        self,
        session_name: Optional[str] = None,
        task_description: str = "",
        tags: Optional[List[str]] = None,
    ) -> str:
        """
        Save current session to disk using SessionManager.

        Args:
            session_name: Optional human-readable name (uses session_id if not provided)
            task_description: Description of the task being worked on
            tags: Optional list of tags for organization

        Returns:
            session_id: Unique session identifier

        Example:
            >>> session_id = memory_manager.save_session(
            ...     session_name="feature-auth",
            ...     task_description="Implementing authentication system",
            ...     tags=["feature", "backend"]
            ... )
            >>> print(f"Saved session: {session_id[:8]}")
        """
        from ..core.session_manager import SessionManager

        # Calculate session duration
        duration_minutes = (datetime.now() - self.session_start).total_seconds() / 60

        # Build complete session state
        state = {
            "working_memory": self.working_memory.to_dict(),
            "episodic_memory": {
                "compressed_history": self.episodic_memory.compressed_history,
                "conversation_turns": [
                    {
                        "id": turn.id,
                        "user_message": turn.user_message.model_dump(mode='json'),
                        "assistant_message": turn.assistant_message.model_dump(mode='json'),
                        "tool_calls": turn.tool_calls,
                        "timestamp": turn.timestamp.isoformat(),
                        "summary": turn.summary,
                        "token_count": turn.token_count,
                    }
                    for turn in self.episodic_memory.conversation_turns
                ],
            },
            "task_context": (
                self.working_memory.task_context.model_dump(mode='json')
                if self.working_memory.task_context
                else None
            ),
            "file_memories": self.file_memory_content,
            "model_name": "unknown",  # Will be overridden if Agent provides it
            "message_count": len(self.working_memory.messages),
            "duration_minutes": duration_minutes,
        }

        # Initialize SessionManager
        sessions_dir = self.persist_directory / "sessions"
        session_manager = SessionManager(sessions_dir=sessions_dir)

        # Save session
        session_id = session_manager.save_session(
            name=session_name,
            state=state,
            task_description=task_description or "No description",
            tags=tags or [],
        )

        return session_id

    def load_session(self, session_id_or_path: str) -> None:
        """
        Load session from disk using SessionManager or legacy path.

        Args:
            session_id_or_path: Session ID (full or short) OR legacy path to session directory

        Raises:
            ValueError: If session not found

        Example:
            >>> # Load by session ID
            >>> memory_manager.load_session("abc12345")
            >>>
            >>> # Load by session name (resolved via SessionManager)
            >>> memory_manager.load_session("feature-auth")
        """
        from ..core.session_manager import SessionManager
        from .models import Message, ConversationTurn

        # Initialize SessionManager
        sessions_dir = self.persist_directory / "sessions"
        session_manager = SessionManager(sessions_dir=sessions_dir)

        # Check if input is a legacy path (Path object or path string with '/')
        if isinstance(session_id_or_path, Path) or "/" in str(session_id_or_path):
            # Legacy format - load directly from path
            session_path = Path(session_id_or_path)
            self._load_legacy_session(session_path)
            return

        # Try loading with SessionManager (new format)
        try:
            state = session_manager.load_session(session_id_or_path)
        except ValueError:
            # Try finding by name
            metadata = session_manager.find_session_by_name(session_id_or_path)
            if metadata:
                state = session_manager.load_session(metadata.session_id)
            else:
                raise ValueError(f"Session not found: {session_id_or_path}")

        # Restore working memory
        if "working_memory" in state:
            self.working_memory.from_dict(state["working_memory"])

        # Restore episodic memory
        if "episodic_memory" in state:
            episodic_data = state["episodic_memory"]
            self.episodic_memory.compressed_history = episodic_data.get("compressed_history", [])

            # Restore conversation turns
            self.episodic_memory.conversation_turns = []
            for turn_data in episodic_data.get("conversation_turns", []):
                user_msg = Message.model_validate(turn_data["user_message"])
                assistant_msg = Message.model_validate(turn_data["assistant_message"])

                turn = ConversationTurn(
                    id=turn_data["id"],
                    user_message=user_msg,
                    assistant_message=assistant_msg,
                    tool_calls=turn_data["tool_calls"],
                    timestamp=datetime.fromisoformat(turn_data["timestamp"]),
                    summary=turn_data.get("summary"),
                    token_count=turn_data.get("token_count"),
                )
                self.episodic_memory.conversation_turns.append(turn)

            # Recalculate tokens
            self.episodic_memory._recalculate_tokens()

        # Restore file memories
        if "file_memories" in state:
            self.file_memory_content = state["file_memories"]

        # Restore session metadata
        metadata = state.get("metadata", {})
        self.session_id = metadata.get("session_id", self.session_id)
        if "created_at" in metadata:
            self.session_start = datetime.fromisoformat(metadata["created_at"])

    def _load_legacy_session(self, session_path: Path) -> None:
        """
        Load session from legacy format (old save_session format).

        Args:
            session_path: Path to session directory
        """
        import json

        # Load episodic memory
        episodic_path = session_path / "episodic_memory.json"
        if episodic_path.exists():
            self.episodic_memory.load_session(episodic_path)

        # Load metadata
        metadata_path = session_path / "metadata.json"
        if metadata_path.exists():
            with open(metadata_path, "r") as f:
                metadata = json.load(f)
                self.session_id = metadata.get("session_id", self.session_id)
                if "session_start" in metadata:
                    self.session_start = datetime.fromisoformat(
                        metadata["session_start"]
                    )

    def get_statistics(self) -> Dict[str, Any]:
        """Get comprehensive memory statistics."""
        return {
            "session_id": self.session_id,
            "session_duration_minutes": (
                datetime.now() - self.session_start
            ).total_seconds()
            / 60,
            "working_memory": {
                "messages": len(self.working_memory.messages),
                "code_contexts": len(self.working_memory.code_contexts),
                "tokens": self.working_memory.get_current_token_count(),
                "summary": self.working_memory.get_summary(),
            },
            "episodic_memory": self.episodic_memory.get_statistics(),
            "semantic_memory": self.semantic_memory.get_statistics(),
            "token_budget": self.get_token_budget(),
        }

    def clear_working_memory(self) -> None:
        """Clear working memory only."""
        self.working_memory.clear()

    def clear_episodic_memory(self) -> None:
        """Clear episodic memory only."""
        self.episodic_memory.clear()

    def clear_all(self) -> None:
        """Clear all memory layers."""
        self.working_memory.clear()
        self.episodic_memory.clear()
        self.semantic_memory.clear()

    def load_file_memories(self, starting_dir: Optional[Path] = None) -> str:
        """
        Load hierarchical file memories from .opencodeagent/memory.md files.

        Loads from:
        1. Enterprise: /etc/opencodeagent/memory.md (Linux/Mac)
        2. User: ~/.opencodeagent/memory.md
        3. Project: .opencodeagent/memory.md (traverses upward from starting_dir)

        Args:
            starting_dir: Directory to start search (default: cwd)

        Returns:
            Combined memory content from all hierarchy levels

        Example:
            >>> manager.load_file_memories()
            >>> # Loads enterprise, user, and project memories
        """
        self.file_memory_content = self.file_loader.load_hierarchy(starting_dir)
        return self.file_memory_content

    def reload_file_memories(self, starting_dir: Optional[Path] = None) -> str:
        """
        Reload file memories (useful after editing memory files).

        Args:
            starting_dir: Directory to start search (default: cwd)

        Returns:
            Updated memory content
        """
        # Create fresh loader to reset loaded_files tracking
        self.file_loader = MemoryFileLoader()
        return self.load_file_memories(starting_dir)

    def quick_add_memory(self, text: str, location: str = "project") -> Path:
        """
        Quick add memory to file (# syntax from user input).

        Args:
            text: Memory text to add
            location: 'project' or 'user'

        Returns:
            Path to file that was updated

        Example:
            >>> manager.quick_add_memory("Always use 2-space indent", "project")
            PosixPath('/path/to/project/.opencodeagent/memory.md')

            >>> # Reload to see the change
            >>> manager.reload_file_memories()
        """
        path = self.file_loader.quick_add(text, location)
        # Auto-reload to include the new memory
        self.reload_file_memories()
        return path

    def init_project_memory(self, path: Optional[Path] = None) -> Path:
        """
        Initialize a new project memory file with template.

        Args:
            path: Path to create file (default: ./.opencodeagent/memory.md)

        Returns:
            Path to created file

        Raises:
            FileExistsError: If file already exists

        Example:
            >>> manager.init_project_memory()
            PosixPath('/path/to/project/.opencodeagent/memory.md')

            >>> # Reload to include the new template
            >>> manager.reload_file_memories()
        """
        created_path = self.file_loader.init_project_memory(path)

        # Auto-reload to include the new template
        # If custom path provided, reload from its parent's parent directory
        # (to find the .opencodeagent directory)
        if path:
            # path is like: /some/dir/.opencodeagent/memory.md
            # We want to search from /some/dir
            search_dir = created_path.parent.parent
            self.reload_file_memories(starting_dir=search_dir)
        else:
            self.reload_file_memories()

        return created_path

    def optimize_context(self, target_tokens: Optional[int] = None) -> None:
        """
        Optimize context to fit within target token budget.

        Args:
            target_tokens: Target token count (uses total_context_tokens if not provided)
        """
        target = target_tokens or (
            self.total_context_tokens - self.system_prompt_tokens
        )
        current = (
            self.working_memory.get_current_token_count()
            + self.episodic_memory.current_token_count
        )

        if current > target:
            # First, compress episodic memory
            self.episodic_memory._compress_old_turns()

            # If still over, compact working memory
            current = (
                self.working_memory.get_current_token_count()
                + self.episodic_memory.current_token_count
            )
            if current > target:
                self.working_memory._compact()
