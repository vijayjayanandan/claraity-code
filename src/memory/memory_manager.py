"""Memory Manager - Orchestrates all memory layers."""

import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from src.observability import get_logger

logger = get_logger("memory")

from src.core.render_meta import RenderMetaRegistry
from src.session.models.message import Message as SessionMessage

from .file_loader import MemoryFileLoader
from .models import (
    CodeContext,
    MemoryType,
    Message,
    MessageRole,
    TaskContext,
)
from .working_memory import WorkingMemory

if TYPE_CHECKING:
    from src.core.streaming import StreamingPipeline
    from src.llm.base import LLMBackend, ProviderDelta
    from src.session.store.memory_store import MessageStore


class MemoryManager:
    """
    Central memory manager that orchestrates all memory layers.
    Handles dynamic token allocation, cross-layer retrieval, and memory persistence.
    """

    def __init__(
        self,
        total_context_tokens: int = 4096,
        working_memory_tokens: int = 2000,
        episodic_memory_tokens: int = 1000,  # Kept for backward compat (ignored)
        system_prompt_tokens: int = 300,
        persist_directory: str = ".claraity",
        load_file_memories: bool = True,
        starting_directory: Path | None = None,
    ):
        """
        Initialize memory manager.

        Args:
            total_context_tokens: Total available context window
            working_memory_tokens: Tokens allocated to working memory
            episodic_memory_tokens: Ignored (kept for backward compat)
            system_prompt_tokens: Tokens reserved for system prompt
            persist_directory: Directory for persistence
            load_file_memories: Whether to load hierarchical file memories on init
            starting_directory: Starting directory for file memory search (default: cwd)
        """
        self.total_context_tokens = total_context_tokens
        self.system_prompt_tokens = system_prompt_tokens

        # Initialize memory layers
        self.working_memory = WorkingMemory(max_tokens=working_memory_tokens)

        # Initialize file-based memory loader
        self.file_loader = MemoryFileLoader()
        self.file_memory_content = ""

        # Persistent memory (agent-managed, cross-session)
        self.persistent_memory_content = ""
        self._persistent_memory_dir: Path | None = None

        # Knowledge base cache

        # Project root for knowledge base loading (avoids Path.cwd() dependency)
        self._project_root: Path = (
            Path(starting_directory).resolve() if starting_directory else Path.cwd()
        )

        # Load file memories if requested
        if load_file_memories:
            self.load_file_memories(starting_directory)

        # Load persistent memory (always attempt)
        self.load_persistent_memory()

        # Session metadata
        self.session_id = str(uuid.uuid4())
        self.session_start = datetime.now()
        self.persist_directory = Path(persist_directory)

        # Key-value store for structured data
        self._key_value_store: dict[str, Any] = {}
        import threading

        self._kv_lock = threading.RLock()  # Thread safety for key-value store

        self._current_turn_id = 0  # Stable turn ID incremented per user message

        # MessageStore integration (Option A: Single Source of Truth)
        # When set, this becomes the primary source for conversation history
        self._message_store: MessageStore | None = None
        self._message_store_session_id: str | None = None
        self._last_parent_uuid: str | None = None  # Track threading for new messages

        # StreamingPipeline (Unified Persistence Architecture)
        # Owned by MemoryManager - the single canonical parser for LLM deltas
        self._streaming_pipeline: StreamingPipeline | None = None

        # Ephemeral render metadata registry (session-scoped)
        # Agent writes approval policy when tool name becomes known during streaming.
        # TUI queries when rendering tool cards. NOT persisted to JSONL.
        self._render_meta = RenderMetaRegistry()

    def set_message_store(
        self,
        store: "MessageStore",
        session_id: str,
    ) -> None:
        """
        Set MessageStore as the primary source of truth for conversation history.

        When set, all conversation context will come from MessageStore.get_llm_context()
        instead of WorkingMemory. New messages will be added to MessageStore.

        This enables unified handling of both new and resumed sessions:
        - New sessions: MessageStore is created, set here, populated as conversation progresses
        - Resumed sessions: JSONL is loaded into MessageStore via SessionHydrator, set here

        Args:
            store: The MessageStore instance (may contain hydrated messages)
            session_id: Session ID for new messages

        Example:
            # For resumed sessions:
            hydrator = SessionHydrator()
            result = hydrator.hydrate(jsonl_path)
            memory_manager.set_message_store(result.store, session_id)

            # For new sessions:
            store = MessageStore()
            memory_manager.set_message_store(store, session_id)
        """
        self._message_store = store
        self._message_store_session_id = session_id

        # Set last_parent_uuid from last message in store (for threading new messages)
        messages = store.get_ordered_messages()
        if messages:
            self._last_parent_uuid = messages[-1].uuid
        else:
            self._last_parent_uuid = None

    @property
    def has_message_store(self) -> bool:
        """Check if MessageStore is configured."""
        return self._message_store is not None

    @property
    def message_store(self) -> Optional["MessageStore"]:
        """Get the MessageStore if configured."""
        return self._message_store

    @property
    def render_meta(self) -> RenderMetaRegistry:
        """Get the ephemeral render metadata registry.

        Agent writes approval policy when tool name becomes known.
        TUI queries when rendering tool cards.
        """
        return self._render_meta

    def add_user_message(
        self, content: str, metadata: dict | None = None, attachments: list | None = None
    ) -> Optional["SessionMessage"]:
        """
        Add user message to memory.

        When MessageStore is configured, adds to MessageStore (single source of truth).
        Also adds to WorkingMemory for backward compatibility and token counting.

        Args:
            content: Message content (text)
            metadata: Optional metadata
            attachments: Optional list of Attachment objects (images, text files)

        Returns:
            SessionMessage if MessageStore is configured, None otherwise
        """
        # Increment turn_id for each user message (stable turn tracking)
        self._current_turn_id += 1

        session_message: SessionMessage | None = None

        # Build multimodal content if attachments present
        message_content = self._build_multimodal_content(content, attachments)

        # Add to MessageStore if configured (Option A: Single Source of Truth)
        if self._message_store is not None and self._message_store_session_id is not None:
            session_message = SessionMessage.create_user(
                content=message_content,  # Can be str or list (multimodal)
                session_id=self._message_store_session_id,
                parent_uuid=self._last_parent_uuid,
                seq=self._message_store.next_seq(),
            )
            self._message_store.add_message(session_message)
            self._last_parent_uuid = session_message.uuid

        # Also add to WorkingMemory for backward compatibility and token counting
        # Note: WorkingMemory only stores text for token counting, not full multimodal
        self.working_memory.add_message(
            role=MessageRole.USER,
            content=content,  # Keep as text for token counting
            metadata=metadata,
        )

        return session_message

    def _build_multimodal_content(
        self, user_input: str, attachments: list | None = None
    ) -> "str | list":
        """
        Convert user text + attachments to OpenAI-compatible multimodal format.

        Uses OpenAI's vision API format which is compatible with:
        - OpenAI GPT-4V / GPT-4o
        - Claude via OpenAI-compatible proxy
        - Other vision-capable models

        Args:
            user_input: User's text message
            attachments: Optional list of Attachment objects

        Returns:
            str: If no attachments, returns plain text
            list: If attachments present, returns content array:
                  [{"type": "text", "text": "..."}, {"type": "image_url", ...}]
        """
        if not attachments:
            return user_input

        # Build multimodal content array
        content = []

        # Add user text first (if any)
        if user_input.strip():
            content.append({"type": "text", "text": user_input})

        # Add each attachment
        for att in attachments:
            if att.kind == "image":
                # Image attachment - use OpenAI vision format with data URL
                # Enhanced: Add structured filename and mime fields
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": att.data_url  # data:image/png;base64,...
                        },
                        "filename": att.filename,  # Structured field for TUI rendering
                        "mime": att.mime,  # Structured field for file type
                    }
                )
            else:
                # Text file attachment - include as text block with filename context
                # Enhanced: Add structured filename and mime fields
                text_content = (
                    att.truncated_text() if hasattr(att, "truncated_text") else (att.text or "")
                )
                content.append(
                    {
                        "type": "text",
                        "text": f"--- BEGIN FILE: {att.filename} ---\n{text_content}\n--- END FILE: {att.filename} ---",
                        "filename": att.filename,  # Structured field (no parsing needed)
                        "mime": att.mime,  # Structured field for file type
                    }
                )

        return content

    @property
    def current_turn_id(self) -> int:
        """Get current turn ID (increments per user message)."""
        return self._current_turn_id

    def add_assistant_message(
        self,
        content: str,
        tool_calls: list[dict] | None = None,
        metadata: dict | None = None,
        stream_id: str | None = None,
        stop_reason: str | None = None,
    ) -> Optional["SessionMessage"]:
        """
        Add assistant message and create conversation turn.

        When MessageStore is configured, adds to MessageStore (single source of truth).
        Also adds to WorkingMemory for backward compatibility and token counting.

        Args:
            content: Message content
            tool_calls: Optional tool calls made (OpenAI format dicts)
            metadata: Optional metadata
            stream_id: Optional stream ID for streaming message collapse
            stop_reason: Optional stop reason (e.g., "complete", "tool_use")

        Returns:
            SessionMessage if MessageStore is configured, None otherwise
        """
        session_message: SessionMessage | None = None

        # Add to MessageStore if configured (Option A: Single Source of Truth)
        if self._message_store is not None and self._message_store_session_id is not None:
            from src.session.models.message import ToolCall, ToolCallFunction

            # Convert tool_calls dicts to ToolCall objects
            session_tool_calls = []
            if tool_calls:
                for tc in tool_calls:
                    function_data = tc.get("function", {})
                    session_tool_calls.append(
                        ToolCall(
                            id=tc.get("id", ""),
                            function=ToolCallFunction(
                                name=function_data.get("name", ""),
                                arguments=function_data.get("arguments", "{}"),
                            ),
                            type=tc.get("type", "function"),
                        )
                    )

            session_message = SessionMessage.create_assistant(
                content=content,
                session_id=self._message_store_session_id,
                parent_uuid=self._last_parent_uuid,
                seq=self._message_store.next_seq(),
                tool_calls=session_tool_calls if session_tool_calls else None,
                stream_id=stream_id,
                stop_reason=stop_reason,
            )
            self._message_store.add_message(session_message)
            self._last_parent_uuid = session_message.uuid

        # Also add to WorkingMemory for backward compatibility and token counting
        self.working_memory.add_message(
            role=MessageRole.ASSISTANT,
            content=content,
            metadata=metadata,
        )

        return session_message

    def persist_system_event(
        self,
        *,
        event_type: str,
        content: str,
        extra: dict[str, Any],
        include_in_llm_context: bool = False,
    ) -> Optional["SessionMessage"]:
        """
        SINGLE WRITER path to persist system events to MessageStore.

        This is the canonical method for persisting system events like
        clarify_request, clarify_response, etc. Agents and UI components
        should use this method instead of directly calling message_store.add_message().

        Args:
            event_type: Event type (e.g., "clarify_request", "clarify_response")
            content: Human-readable content for display
            extra: Event-specific data dict
            include_in_llm_context: Whether to include in LLM context (default: False)

        Returns:
            SessionMessage if MessageStore is configured, None otherwise
        """
        if self._message_store is None or self._message_store_session_id is None:
            return None

        msg = SessionMessage.create_system(
            content=content,
            session_id=self._message_store_session_id,
            seq=self._message_store.next_seq(),
            event_type=event_type,
            include_in_llm_context=include_in_llm_context,
            extra=extra,
        )
        self._message_store.add_message(msg)
        return msg

    def add_tool_result(
        self,
        tool_call_id: str,
        content: str,
        tool_name: str | None = None,
        status: str = "success",
        duration_ms: int | None = None,
        exit_code: int | None = None,
    ) -> Optional["SessionMessage"]:
        """
        Add tool result message to MessageStore.

        This creates a proper tool result message that matches the tool_call_id
        from the assistant's tool call. Required for valid LLM context.

        Args:
            tool_call_id: ID of the tool call this result responds to
            content: Tool output content
            tool_name: Optional tool name (for logging/display)
            status: Tool execution status ("success", "error", "timeout")
            duration_ms: Optional execution duration in milliseconds
            exit_code: Optional exit code (for command tools)

        Returns:
            SessionMessage if MessageStore is configured, None otherwise
        """
        session_message: SessionMessage | None = None

        if self._message_store is not None and self._message_store_session_id is not None:
            session_message = SessionMessage.create_tool(
                tool_call_id=tool_call_id,
                content=content,
                session_id=self._message_store_session_id,
                parent_uuid=self._last_parent_uuid,
                seq=self._message_store.next_seq(),
                status=status,
                duration_ms=duration_ms,
                exit_code=exit_code,
            )
            self._message_store.add_message(session_message)
            self._last_parent_uuid = session_message.uuid

        return session_message

    # =========================================================================
    # Streaming Pipeline (Unified Persistence Architecture)
    # =========================================================================

    def start_assistant_stream(
        self,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        """
        Initialize streaming pipeline for new assistant message.

        Call this before processing provider deltas for a new assistant response.
        The pipeline will accumulate deltas and produce a finalized Message
        when the stream completes.

        Args:
            provider: Provider name (e.g., "openai", "anthropic")
            model: Model name

        Example:
            >>> memory.start_assistant_stream(provider="openai", model="gpt-4")
            >>> for delta in llm_stream:
            ...     message = memory.process_provider_delta(delta)
            ...     if message:
            ...         print(f"Stream complete: {len(message.segments)} segments")
        """
        from src.core.streaming import StreamingPipeline

        if self._message_store is None or self._message_store_session_id is None:
            raise RuntimeError("MessageStore not configured. Call set_message_store() first.")

        self._streaming_pipeline = StreamingPipeline(
            session_id=self._message_store_session_id,
            parent_uuid=self._last_parent_uuid,
            provider=provider,
            model=model,
        )

    def process_provider_delta(
        self,
        delta: "ProviderDelta",
    ) -> Optional["SessionMessage"]:
        """
        Process a provider delta through the canonical streaming pipeline.

        This is the SINGLE entry point for processing LLM streaming responses.
        The pipeline handles all structural parsing (code fences, tool calls,
        thinking blocks) and produces fully-parsed segments.

        When the stream finalizes (delta.finish_reason is set), the complete
        Message is written to MessageStore and returned.

        Args:
            delta: ProviderDelta from provider adapter

        Returns:
            Finalized SessionMessage when stream completes, None during streaming.

        Raises:
            RuntimeError: If start_assistant_stream() wasn't called first.

        Example:
            >>> memory.start_assistant_stream()
            >>> for delta in llm_stream:
            ...     message = memory.process_provider_delta(delta)
            ...     if message:
            ...         # Stream complete - message has segments
            ...         for seg in message.segments:
            ...             print(f"Segment: {type(seg).__name__}")
        """
        if self._streaming_pipeline is None:
            raise RuntimeError("No active stream. Call start_assistant_stream() first.")

        if self._message_store is None:
            raise RuntimeError("MessageStore not configured. Call set_message_store() first.")

        # Process delta through canonical pipeline
        message = self._streaming_pipeline.process_delta(delta)

        if message is not None:
            # Stream finalized - write to MessageStore (SINGLE WRITER)
            message.meta.seq = self._message_store.next_seq()
            self._message_store.add_message(message)
            self._last_parent_uuid = message.uuid

            # Reset pipeline for next stream
            self._streaming_pipeline = None

            # Also add to WorkingMemory for backward compatibility
            self.working_memory.add_message(
                role=MessageRole.ASSISTANT,
                content=message.content or "",
                metadata=None,
            )

            return message

        return None

    def get_streaming_state(self) -> Optional["SessionMessage"]:
        """
        Get current in-flight message state for live UI updates.

        This returns the current accumulated state of the streaming message
        without finalizing it. Use this for live UI rendering during streaming.

        Returns:
            Current Message state (not finalized), or None if not streaming.

        Example:
            >>> memory.start_assistant_stream()
            >>> # During streaming, get current state for UI
            >>> current = memory.get_streaming_state()
            >>> if current:
            ...     for seg in current.segments:
            ...         render_segment(seg)
        """
        if self._streaming_pipeline is None:
            return None

        return self._streaming_pipeline.get_current_state()

    def get_partial_text(self) -> str:
        """Return accumulated text from in-flight stream, or empty string."""
        if self._streaming_pipeline and self._streaming_pipeline._state:
            return self._streaming_pipeline._state.full_text_content
        return ""

    @property
    def is_streaming(self) -> bool:
        """Check if currently processing an assistant stream."""
        return self._streaming_pipeline is not None

    def add_code_context(self, code_context: CodeContext) -> None:
        """
        Add code context to working memory.

        Args:
            code_context: CodeContext to add
        """
        self.working_memory.add_code_context(code_context)

    def set_task_context(self, task_context: TaskContext) -> None:
        """
        Set current task context.

        Args:
            task_context: TaskContext to set
        """
        self.working_memory.set_task_context(task_context)

    def get_context_for_llm(
        self,
        system_prompt: str,
        include_episodic: bool = True,  # Kept for backward compat (ignored)
        include_file_memories: bool = True,
        max_context_messages: int | None = None,
    ) -> list[dict[str, str]]:
        """
        Build complete context for LLM from all memory layers.

        When MessageStore is configured (Option A), conversation history comes from
        MessageStore.get_llm_context() instead of WorkingMemory. This provides:
        - Unified handling for both new and resumed sessions
        - Full message fidelity (tool_calls, tool_call_id preserved)
        - Proper streaming collapse and compaction awareness

        Args:
            system_prompt: System prompt to include
            include_episodic: Ignored (kept for backward compat)
            include_file_memories: Whether to include file-based memories (default: True)
            max_context_messages: Optional limit on conversation messages

        Returns:
            list of message dictionaries for LLM
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

        # 2a. Persistent memory is injected by ContextBuilder into the system
        # prompt (not as a separate system message) so it survives the system
        # message filtering in build_context().

        # 2b. Knowledge base is now injected by ContextBuilder directly
        # into the system prompt (not as a separate system message).

        # 3. Conversation history
        # Option A: Use MessageStore if configured (single source of truth)
        if self._message_store is not None:
            # Get LLM-ready context from MessageStore
            # This handles compaction, streaming collapse, and proper message format
            conversation_context = self._message_store.get_llm_context(
                max_messages=max_context_messages
            )

            # Debug: Log tool messages being retrieved
            tool_msgs = [m for m in conversation_context if m.get("role") == "tool"]
            if tool_msgs:
                logger.warning(
                    f"[CONTEXT_BUILD] Retrieved {len(tool_msgs)} tool messages from MessageStore: "
                    f"{[m.get('tool_call_id') for m in tool_msgs]}"
                )

            # Filter out system messages (we have our own system prompt)
            conversation_context = [
                msg for msg in conversation_context if msg.get("role") != "system"
            ]
            context.extend(conversation_context)
        else:
            # Fallback: Use WorkingMemory (legacy path)
            working_context = self.working_memory.get_context_for_llm()
            context.extend(working_context)

        return context

    def get_token_budget(self) -> dict[str, int]:
        """
        Get current token allocation across memory layers.

        Returns:
            Dictionary with token counts
        """
        working_tokens = self.working_memory.get_current_token_count()

        return {
            "total_available": self.total_context_tokens,
            "system_prompt_reserved": self.system_prompt_tokens,
            "working_memory": working_tokens,
            "remaining": self.total_context_tokens
            - self.system_prompt_tokens
            - working_tokens,
        }

    def save_session(
        self,
        session_name: str | None = None,
        task_description: str = "",
        tags: list[str] | None = None,
        permission_mode: str = "normal",
    ) -> str:
        """
        Save current session to disk using SessionManager.

        Args:
            session_name: Optional human-readable name (uses session_id if not provided)
            task_description: Description of the task being worked on
            tags: Optional list of tags for organization
            permission_mode: Current permission mode (plan/normal/auto) to save with session

        Returns:
            session_id: Unique session identifier

        Example:
            >>> session_id = memory_manager.save_session(
            ...     session_name="feature-auth",
            ...     task_description="Implementing authentication system",
            ...     tags=["feature", "backend"],
            ...     permission_mode="normal"
            ... )
            >>> print(f"Saved session: {session_id[:8]}")
        """
        from ..core.session_manager import SessionManager

        # Calculate session duration
        duration_minutes = (datetime.now() - self.session_start).total_seconds() / 60

        # Build complete session state
        state = {
            "working_memory": self.working_memory.to_dict(),
            "task_context": (
                self.working_memory.task_context.model_dump(mode="json")
                if self.working_memory.task_context
                else None
            ),
            "file_memories": self.file_memory_content,
            "persistent_memory": self.persistent_memory_content,
            "model_name": "unknown",  # Will be overridden if Agent provides it
            "message_count": len(self.working_memory.messages),
            "duration_minutes": duration_minutes,
            "permission_mode": permission_mode,
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

        # Restore file memories
        if "file_memories" in state:
            self.file_memory_content = state["file_memories"]

        # Restore persistent memory (reload from disk — it may have changed
        # since the session was saved, which is the whole point)
        self.load_persistent_memory()

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

        # Load metadata
        metadata_path = session_path / "metadata.json"
        if metadata_path.exists():
            with open(metadata_path) as f:
                metadata = json.load(f)
                self.session_id = metadata.get("session_id", self.session_id)
                if "session_start" in metadata:
                    self.session_start = datetime.fromisoformat(metadata["session_start"])

    def get_statistics(self) -> dict[str, Any]:
        """Get comprehensive memory statistics."""
        return {
            "session_id": self.session_id,
            "session_duration_minutes": (datetime.now() - self.session_start).total_seconds() / 60,
            "working_memory": {
                "messages": len(self.working_memory.messages),
                "code_contexts": len(self.working_memory.code_contexts),
                "tokens": self.working_memory.get_current_token_count(),
                "summary": self.working_memory.get_summary(),
            },
            "token_budget": self.get_token_budget(),
        }

    def clear_working_memory(self) -> None:
        """Clear working memory only."""
        self.working_memory.clear()

    def clear_all(self) -> None:
        """Clear all memory layers and ephemeral state."""
        self.working_memory.clear()
        # Clear ephemeral session state
        self._render_meta.clear()
        if self._message_store:
            self._message_store.clear_tool_state()

    def load_file_memories(self, starting_dir: Path | None = None) -> str:
        """
        Load hierarchical file memories from .claraity/memory.md files.

        Loads from:
        1. Enterprise: /etc/claraity/memory.md (Linux/Mac)
        2. User: ~/.claraity/memory.md
        3. Project: .claraity/memory.md (traverses upward from starting_dir)

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

    def reload_file_memories(self, starting_dir: Path | None = None) -> str:
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
            PosixPath('/path/to/project/.claraity/memory.md')

            >>> # Reload to see the change
            >>> manager.reload_file_memories()
        """
        path = self.file_loader.quick_add(text, location)
        # Auto-reload to include the new memory
        self.reload_file_memories()
        return path

    def init_project_memory(self, path: Path | None = None) -> Path:
        """
        Initialize a new project memory file with template.

        Args:
            path: Path to create file (default: ./.claraity/memory.md)

        Returns:
            Path to created file

        Raises:
            FileExistsError: If file already exists

        Example:
            >>> manager.init_project_memory()
            PosixPath('/path/to/project/.claraity/memory.md')

            >>> # Reload to include the new template
            >>> manager.reload_file_memories()
        """
        created_path = self.file_loader.init_project_memory(path)

        # Auto-reload to include the new template
        # If custom path provided, reload from its parent's parent directory
        # (to find the .claraity directory)
        if path:
            # path is like: /some/dir/.claraity/memory.md
            # We want to search from /some/dir
            search_dir = created_path.parent.parent
            self.reload_file_memories(starting_dir=search_dir)
        else:
            self.reload_file_memories()

        return created_path

    # =========================================================================
    # Persistent Memory (agent-managed, cross-session)
    # =========================================================================

    @property
    def persistent_memory_dir(self) -> Path:
        """Get the persistent memory directory path (.claraity/memory/)."""
        if self._persistent_memory_dir is not None:
            return self._persistent_memory_dir
        return self._project_root / ".claraity" / "memory"

    def load_persistent_memory(self) -> str:
        """
        Load the agent-managed persistent memory index (MEMORY.md).

        Reads .claraity/memory/MEMORY.md if it exists. Creates the directory
        and an empty MEMORY.md if they don't exist.

        This is separate from file_memory_content (developer-authored project
        instructions). Persistent memory is written by the agent across sessions
        to remember user preferences, feedback, project context, and references.

        Returns:
            Content of MEMORY.md, or empty string if none exists.
        """
        memory_dir = self.persistent_memory_dir
        index_path = memory_dir / "MEMORY.md"

        # Ensure directory exists
        try:
            memory_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("persistent_memory_dir_create_failed", error=str(e))
            self.persistent_memory_content = ""
            return ""

        # Create empty MEMORY.md if it doesn't exist
        if not index_path.exists():
            try:
                index_path.write_text(
                    "# ClarAIty Agent Memory\n",
                    encoding="utf-8",
                )
                logger.info("persistent_memory_index_created", path=str(index_path))
            except OSError as e:
                logger.warning("persistent_memory_index_create_failed", error=str(e))

        # Load the index
        try:
            if index_path.exists():
                content = index_path.read_text(encoding="utf-8").strip()
                self.persistent_memory_content = content
                logger.info(
                    "persistent_memory_loaded",
                    path=str(index_path),
                    length=len(content),
                )
                return content
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("persistent_memory_load_failed", error=str(e))

        self.persistent_memory_content = ""
        return ""

    def reload_persistent_memory(self) -> str:
        """Reload persistent memory (useful after agent writes new memories)."""
        return self.load_persistent_memory()

    @staticmethod
    def _fix_orphaned_tool_calls(context: list) -> list:
        """
        Fix tool_call/tool_result pairing for API compliance.

        Scans messages for tool_use blocks without matching tool_result and
        inserts synthetic results. Returns a new list (does NOT persist changes
        -- this is only used for the summarization LLM call).
        """
        # Collect tool_call ids from assistant messages
        tool_call_ids = {}  # id -> (name, index_in_context)
        for i, msg in enumerate(context):
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    tc_id = tc.get("id")
                    if tc_id:
                        tc_name = tc.get("function", {}).get("name", "unknown")
                        tool_call_ids[tc_id] = (tc_name, i)

        # Collect existing tool_results
        existing_results = {}
        for msg in context:
            if msg.get("role") == "tool":
                tc_id = msg.get("tool_call_id")
                if tc_id:
                    existing_results[tc_id] = msg

        orphaned = set(tool_call_ids.keys()) - set(existing_results.keys())

        if orphaned:
            logger.info(
                "compact_fixing_orphaned_tool_calls",
                orphan_count=len(orphaned),
                orphan_ids=list(orphaned),
            )

            # Create synthetics for orphans
            for tc_id in orphaned:
                tc_name, _ = tool_call_ids[tc_id]
                existing_results[tc_id] = {
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "name": tc_name,
                    "content": "Tool execution was interrupted.",
                }

        # No tool_calls at all — nothing to fix
        if not tool_call_ids:
            return context

        # Rebuild context with tool_results in correct positions
        # (always reorder, not just when orphans exist — misplaced
        # tool_results also cause API errors)
        result = []
        placed = set()
        for msg in context:
            if msg.get("role") == "tool":
                continue  # re-insert in correct position below
            result.append(msg)
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    tc_id = tc.get("id")
                    if tc_id and tc_id in existing_results and tc_id not in placed:
                        result.append(existing_results[tc_id])
                        placed.add(tc_id)

        return result

    async def compact_conversation_async(
        self,
        current_input_tokens: int,
        llm_backend: "LLMBackend",
    ) -> int:
        """
        Compact conversation via LLM summarization (async, non-blocking).

        Sends the actual structured conversation messages to the LLM with a
        summarization system prompt — no serialization to text blob.
        This avoids token inflation that caused the 378K prompt-too-long error.
        """
        if self._message_store is None:
            logger.warning("compact_conversation_skipped: no MessageStore")
            return 0

        context_dicts = self._message_store.get_llm_context()
        if len(context_dicts) <= 4:
            return 0

        evicted_count = len(context_dicts)

        # Fix orphaned tool_calls before sending to summarization LLM.
        # The main agent runs _fix_orphaned_tool_calls on every LLM call,
        # but the compaction path was missing this — causing API errors when
        # the conversation has interrupted tool_use blocks (e.g., Ctrl+C).
        context_dicts = self._fix_orphaned_tool_calls(context_dicts)

        from src.memory.compaction import PrioritizedSummarizer

        token_budget = min(6000, current_input_tokens // 6)
        summarizer = PrioritizedSummarizer(
            token_budget=token_budget,
            llm_caller=None,
        )

        # Build summarization messages: system prompt + actual conversation + instruction
        # Key insight: send native structured messages instead of serializing to text.
        # The conversation messages are already in the right format from get_llm_context().
        summarize_system = {
            "role": "system",
            "content": (
                "You are a summarization assistant. You will receive a conversation "
                "between a user and an AI coding agent. Summarize it for continuation."
            ),
        }

        summarize_instruction = {
            "role": "user",
            "content": (
                "The conversation above is between a user and an AI coding agent. "
                "Create a continuation summary with these sections IN ORDER OF IMPORTANCE:\n\n"
                "## Goal and Key Decisions\n"
                "What is the user trying to accomplish? What important decisions were made?\n\n"
                "## All User Messages\n"
                "Include ALL user messages in chronological order.\n\n"
                "## Code Snippets\n"
                "Include actual code that was written or discussed.\n\n"
                "## Errors and Fixes\n"
                "What went wrong and how was it fixed?\n\n"
                "## Files Modified\n"
                "Which files were created/modified and why?\n\n"
                "## Current State\n"
                "What was just completed? What's the logical next step?\n\n"
                "IMPORTANT: Preserve user messages VERBATIM. Include actual code snippets. "
                f"Target approximately {token_budget} tokens.\n\n"
                "Output the summary in clean markdown format."
            ),
        }

        messages = [summarize_system] + context_dicts + [summarize_instruction]

        logger.info(
            "compact_sending_native_messages",
            conversation_messages=len(context_dicts),
            total_messages=len(messages),
        )

        # Use the same async streaming path as normal TUI conversation
        try:
            summary_parts = []
            async for delta in llm_backend.generate_provider_deltas_async(messages):
                if delta.text_delta:
                    summary_parts.append(delta.text_delta)
            summary = "".join(summary_parts)

            if not summary or summarizer.count_tokens(summary) > token_budget * 1.2:
                logger.warning("compact_async: LLM summary empty or over budget, using fallback")
                summary = summarizer._generate_deterministic_summary(context_dicts)
        except Exception as e:
            logger.error("compact_conversation_async_llm_failed", error=str(e))
            try:
                summary = summarizer._generate_deterministic_summary(context_dicts)
            except Exception as e2:
                logger.error("compact_conversation_async_fallback_failed", error=str(e2))
                return 0

        logger.info(
            "compact_conversation_async",
            evicted_count=evicted_count,
            summary_length=len(summary),
            input_tokens=current_input_tokens,
        )

        return self._message_store.compact(
            summary_content=summary,
            evicted_count=evicted_count,
            pre_tokens=current_input_tokens,
        )

    def set_value(self, key: str, value: Any) -> None:
        """
        Store structured key-value data.

        Thread-safe storage for preserving structured data (dicts, lists, etc.)
        without flattening to strings. Used by AgentInterface.update_memory().

        Args:
            key: Memory key
            value: Value to store (any JSON-serializable type)

        Example:
            memory.set_value('test_results', {'passed': 10, 'failed': 2})
        """
        with self._kv_lock:
            self._key_value_store[key] = value

    def get_value(self, key: str, default: Any = None) -> Any:
        """
        Retrieve structured key-value data.

        Thread-safe retrieval of structured data stored via set_value().
        Used by AgentInterface.get_memory().

        Args:
            key: Memory key
            default: Default value if key not found

        Returns:
            Stored value, or default if not found

        Example:
            results = memory.get_value('test_results', {'passed': 0, 'failed': 0})
        """
        with self._kv_lock:
            return self._key_value_store.get(key, default)
