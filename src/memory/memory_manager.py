"""Memory Manager - Orchestrates all memory layers."""

from typing import List, Optional, Dict, Any, Tuple
from pathlib import Path
from datetime import datetime
import uuid

from .working_memory import WorkingMemory
from .episodic_memory import EpisodicMemory
from .semantic_memory import SemanticMemory
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
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
        persist_directory: str = "./data",
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
    ) -> List[Dict[str, str]]:
        """
        Build complete context for LLM from all memory layers.

        Args:
            system_prompt: System prompt to include
            include_episodic: Whether to include episodic memory summary
            include_semantic_query: Optional query to retrieve from semantic memory

        Returns:
            List of message dictionaries for LLM
        """
        context = []

        # 1. System prompt
        context.append({"role": "system", "content": system_prompt})

        # 2. Episodic memory summary (if requested)
        if include_episodic and self.episodic_memory.conversation_turns:
            episodic_summary = self.episodic_memory.get_context_summary()
            if episodic_summary:
                context.append(
                    {
                        "role": "system",
                        "content": f"Previous conversation context:\n{episodic_summary}",
                    }
                )

        # 3. Semantic memory retrieval (if query provided)
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

        # 4. Working memory (current conversation)
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

    def save_session(self, session_name: Optional[str] = None) -> Path:
        """
        Save current session to disk.

        Args:
            session_name: Optional session name (uses session_id if not provided)

        Returns:
            Path to saved session
        """
        name = session_name or self.session_id
        session_dir = self.persist_directory / "sessions" / name
        session_dir.mkdir(parents=True, exist_ok=True)

        # Save episodic memory
        episodic_path = session_dir / "episodic_memory.json"
        self.episodic_memory.save_session(episodic_path)

        # Save session metadata
        import json

        metadata_path = session_dir / "metadata.json"
        metadata = {
            "session_id": self.session_id,
            "session_start": self.session_start.isoformat(),
            "session_end": datetime.now().isoformat(),
            "token_budget": self.get_token_budget(),
            "statistics": self.get_statistics(),
        }

        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        return session_dir

    def load_session(self, session_path: Path) -> None:
        """
        Load session from disk.

        Args:
            session_path: Path to session directory
        """
        # Load episodic memory
        episodic_path = session_path / "episodic_memory.json"
        if episodic_path.exists():
            self.episodic_memory.load_session(episodic_path)

        # Load metadata
        metadata_path = session_path / "metadata.json"
        if metadata_path.exists():
            import json

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
