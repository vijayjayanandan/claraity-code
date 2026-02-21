"""Memory Manager - Orchestrates all memory layers."""

from typing import List, Optional, Dict, Any, Tuple, TYPE_CHECKING
from pathlib import Path
from datetime import datetime
import uuid

from src.observability import get_logger

logger = get_logger("memory")

from .working_memory import WorkingMemory
from .episodic_memory import EpisodicMemory
from .semantic_memory import SemanticMemory
from .file_loader import MemoryFileLoader
from .observation_store import (
    ObservationStore,
    Observation,
    ObservationPointer,
    Importance,
    classify_importance,
)
from .models import (
    Message,
    MessageRole,
    ConversationTurn,
    CodeContext,
    TaskContext,
    MemoryType,
)

from src.core.render_meta import RenderMetaRegistry

if TYPE_CHECKING:
    from src.session.store.memory_store import MessageStore
    from src.session.models.message import Message as SessionMessage
    from src.core.streaming import StreamingPipeline
    from src.llm.base import ProviderDelta


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
        embedding_model: Optional[str] = None,
        embedding_api_key: Optional[str] = None,
        embedding_api_key_env: str = "EMBEDDING_API_KEY",
        embedding_base_url: Optional[str] = None,
        embedding_dimension: Optional[int] = None,
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
            embedding_model: Embedding model for semantic memory (from .env EMBEDDING_MODEL)
            embedding_api_key: API key for embedding service (optional)
            embedding_api_key_env: Environment variable for embedding API key (default: EMBEDDING_API_KEY)
            embedding_base_url: Base URL for embedding API (from .env EMBEDDING_BASE_URL)
            embedding_dimension: Dimension of embeddings (from .env EMBEDDING_DIMENSION)
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
            api_key=embedding_api_key,
            api_key_env=embedding_api_key_env,
            base_url=embedding_base_url,
            embedding_dimension=embedding_dimension,
        )

        # Initialize file-based memory loader
        self.file_loader = MemoryFileLoader()
        self.file_memory_content = ""

        # Knowledge base cache
        self._knowledge_core_content: Optional[str] = None

        # Project root for knowledge base loading (avoids Path.cwd() dependency)
        self._project_root: Path = Path(starting_directory).resolve() if starting_directory else Path.cwd()

        # Load file memories if requested
        if load_file_memories:
            self.load_file_memories(starting_directory)

        # Session metadata
        self.session_id = str(uuid.uuid4())
        self.session_start = datetime.now()
        self.persist_directory = Path(persist_directory)

        # Key-value store for structured data
        self._key_value_store: Dict[str, Any] = {}
        import threading
        self._kv_lock = threading.RLock()  # Thread safety for key-value store

        # Phase 2: ObservationStore for reversible tool output masking
        self.observation_store = ObservationStore(
            db_path=f"{persist_directory}/observations.db",
        )
        self._current_turn_id = 0  # Stable turn ID incremented per user message

        # MessageStore integration (Option A: Single Source of Truth)
        # When set, this becomes the primary source for conversation history
        self._message_store: Optional["MessageStore"] = None
        self._message_store_session_id: Optional[str] = None
        self._last_parent_uuid: Optional[str] = None  # Track threading for new messages

        # StreamingPipeline (Unified Persistence Architecture)
        # Owned by MemoryManager - the single canonical parser for LLM deltas
        self._streaming_pipeline: Optional["StreamingPipeline"] = None

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
        self, content: str, metadata: Optional[Dict] = None, attachments: Optional[List] = None
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

        session_message: Optional["SessionMessage"] = None

        # Build multimodal content if attachments present
        message_content = self._build_multimodal_content(content, attachments)

        # Add to MessageStore if configured (Option A: Single Source of Truth)
        if self._message_store is not None and self._message_store_session_id is not None:
            from src.session.models.message import Message as SessionMessage

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
        self,
        user_input: str,
        attachments: Optional[List] = None
    ) -> 'str | list':
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
            content.append({
                "type": "text",
                "text": user_input
            })

        # Add each attachment
        for att in attachments:
            if att.kind == "image":
                # Image attachment - use OpenAI vision format with data URL
                # Enhanced: Add structured filename and mime fields
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": att.data_url  # data:image/png;base64,...
                    },
                    "filename": att.filename,  # Structured field for TUI rendering
                    "mime": att.mime  # Structured field for file type
                })
            else:
                # Text file attachment - include as text block with filename context
                # Enhanced: Add structured filename and mime fields
                text_content = att.truncated_text() if hasattr(att, 'truncated_text') else (att.text or "")
                content.append({
                    "type": "text",
                    "text": f"--- BEGIN FILE: {att.filename} ---\n{text_content}\n--- END FILE: {att.filename} ---",
                    "filename": att.filename,  # Structured field (no parsing needed)
                    "mime": att.mime  # Structured field for file type
                })

        return content

    @property
    def current_turn_id(self) -> int:
        """Get current turn ID (increments per user message)."""
        return self._current_turn_id

    def add_assistant_message(
        self,
        content: str,
        tool_calls: Optional[List[Dict]] = None,
        metadata: Optional[Dict] = None,
        stream_id: Optional[str] = None,
        stop_reason: Optional[str] = None,
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
        session_message: Optional["SessionMessage"] = None

        # Add to MessageStore if configured (Option A: Single Source of Truth)
        if self._message_store is not None and self._message_store_session_id is not None:
            from src.session.models.message import Message as SessionMessage, ToolCall, ToolCallFunction

            # Convert tool_calls dicts to ToolCall objects
            session_tool_calls = []
            if tool_calls:
                for tc in tool_calls:
                    function_data = tc.get("function", {})
                    session_tool_calls.append(ToolCall(
                        id=tc.get("id", ""),
                        function=ToolCallFunction(
                            name=function_data.get("name", ""),
                            arguments=function_data.get("arguments", "{}")
                        ),
                        type=tc.get("type", "function")
                    ))

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

        return session_message

    def persist_system_event(
        self,
        *,
        event_type: str,
        content: str,
        extra: Dict[str, Any],
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

        from src.session.models.message import Message as SessionMessage

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
        tool_name: Optional[str] = None,
        status: str = "success",
        duration_ms: Optional[int] = None,
        exit_code: Optional[int] = None,
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
        session_message: Optional["SessionMessage"] = None

        if self._message_store is not None and self._message_store_session_id is not None:
            from src.session.models.message import Message as SessionMessage

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
        provider: Optional[str] = None,
        model: Optional[str] = None,
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
            raise RuntimeError(
                "MessageStore not configured. Call set_message_store() first."
            )

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
            raise RuntimeError(
                "No active stream. Call start_assistant_stream() first."
            )

        if self._message_store is None:
            raise RuntimeError(
                "MessageStore not configured. Call set_message_store() first."
            )

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

    def add_tool_observation(
        self,
        tool_name: str,
        args: Any,
        content: str,
        importance: Optional[Importance] = None,
        metadata: Optional[Dict[str, Any]] = None,
        inline_threshold_tokens: int = 500,
    ) -> Tuple[str, bool]:
        """
        Store tool output in ObservationStore and decide inline vs pointer.

        This implements Phase 2 of context management: reversible masking.
        Large or old tool outputs are stored externally with a pointer in context.

        Args:
            tool_name: Name of the tool that produced output
            args: Tool arguments (for deduplication)
            content: Full tool output content
            importance: Importance level (auto-classified if None)
            metadata: Optional metadata
            inline_threshold_tokens: Token threshold for inline vs pointer decision

        Returns:
            Tuple of (content_to_use, is_pointer):
                - content_to_use: Either full content or pointer string
                - is_pointer: True if content was stored as pointer

        Example:
            >>> content, is_pointer = memory.add_tool_observation(
            ...     tool_name="read_file",
            ...     args={"path": "/src/app.py"},
            ...     content="def main():\\n    print('Hello')",
            ... )
            >>> if is_pointer:
            ...     print(f"Stored as pointer: {content}")
        """
        # Auto-classify importance if not provided
        if importance is None:
            importance = classify_importance(tool_name, content)

        # Save to ObservationStore
        observation = self.observation_store.save(
            tool_name=tool_name,
            args=args,
            content=content,
            turn_id=self._current_turn_id,
            importance=importance,
            metadata=metadata,
        )

        # Decision: inline vs pointer
        # Inline if: small AND (recent OR critical)
        is_recent = True  # Current turn is always recent
        is_small = observation.token_count <= inline_threshold_tokens
        is_critical = importance == Importance.CRITICAL

        if is_small and (is_recent or is_critical):
            # Keep inline
            return content, False
        else:
            # Use pointer
            pointer = observation.to_pointer()
            return pointer, True

    def rehydrate_observation(self, pointer: str) -> Optional[str]:
        """
        Rehydrate a pointer to its full content.

        Args:
            pointer: Pointer string like [[OBS#abc123 ...]]

        Returns:
            Full content if found, None otherwise
        """
        return self.observation_store.rehydrate(pointer)

    def mask_old_observations(
        self,
        mask_age: int = 15,
        exclude_critical: bool = True,
    ) -> int:
        """
        Convert old inline tool outputs to pointers.

        This is called during context compaction to reduce token usage
        while preserving recoverability.

        Args:
            mask_age: Mask observations older than this many turns
            exclude_critical: If True, don't mask critical observations

        Returns:
            Number of observations that could be masked
        """
        maskable = self.observation_store.find_for_masking(
            current_turn_id=self._current_turn_id,
            mask_age=mask_age,
            exclude_critical=exclude_critical,
        )
        return len(maskable)

    def get_observation_stats(self) -> Dict[str, Any]:
        """Get statistics about stored observations."""
        return self.observation_store.get_stats()

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
        max_context_messages: Optional[int] = None,
    ) -> List[Dict[str, str]]:
        """
        Build complete context for LLM from all memory layers.

        When MessageStore is configured (Option A), conversation history comes from
        MessageStore.get_llm_context() instead of WorkingMemory. This provides:
        - Unified handling for both new and resumed sessions
        - Full message fidelity (tool_calls, tool_call_id preserved)
        - Proper streaming collapse and compaction awareness

        Args:
            system_prompt: System prompt to include
            include_episodic: Whether to include episodic memory summary
            include_semantic_query: Optional query to retrieve from semantic memory
            include_file_memories: Whether to include file-based memories (default: True)
            max_context_messages: Optional limit on conversation messages

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

        # 2b. Knowledge base is now injected by ContextBuilder directly
        # into the system prompt (not as a separate system message).

        # 3. Episodic memory summary (if requested)
        # Skip if using MessageStore (it has its own compaction handling)
        if include_episodic and self._message_store is None and self.episodic_memory.conversation_turns:
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

        # 5. Conversation history
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
                msg for msg in conversation_context
                if msg.get("role") != "system"
            ]
            context.extend(conversation_context)
        else:
            # Fallback: Use WorkingMemory (legacy path)
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
        """Clear all memory layers and ephemeral state."""
        self.working_memory.clear()
        self.episodic_memory.clear()
        self.semantic_memory.clear()
        # Clear ephemeral session state
        self._render_meta.clear()
        if self._message_store:
            self._message_store.clear_tool_state()

    def load_file_memories(self, starting_dir: Optional[Path] = None) -> str:
        """
        Load hierarchical file memories from .clarity/memory.md files.

        Loads from:
        1. Enterprise: /etc/clarity/memory.md (Linux/Mac)
        2. User: ~/.clarity/memory.md
        3. Project: .clarity/memory.md (traverses upward from starting_dir)

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

    # Knowledge files loaded into agent context, in order.
    # core.md is capped at 200 lines; decisions/lessons at 100 lines each.
    # Others have no hard cap (written by knowledge-builder to be concise).
    _KNOWLEDGE_FILES = [
        ("core.md", 200),
        ("architecture.md", 150),
        ("file-guide.md", 150),
        ("conventions.md", 150),
        ("decisions.md", 100),
        ("lessons.md", 100),
    ]

    def _load_knowledge_base(self, force_reload: bool = False) -> str:
        """Load all knowledge base files into a single combined string.

        Loads core.md, architecture.md, file-guide.md, conventions.md,
        decisions.md, and lessons.md from .clarity/knowledge/ and combines
        them with section separators.
        core.md is capped at 200 lines; decisions/lessons at 100 lines each.

        Args:
            force_reload: If True, bypass cache and reload from disk

        Returns:
            Combined knowledge content or empty string if no files found
        """
        if not force_reload and self._knowledge_core_content is not None:
            return self._knowledge_core_content

        knowledge_dir = self._project_root / ".clarity" / "knowledge"

        if not knowledge_dir.exists():
            self._knowledge_core_content = ""
            return ""

        sections = []
        for filename, max_lines in self._KNOWLEDGE_FILES:
            filepath = knowledge_dir / filename
            if not filepath.exists():
                continue

            try:
                content = filepath.read_text(encoding='utf-8')
                if not content.strip():
                    continue

                # Apply line cap if set (only core.md has one)
                if max_lines > 0:
                    lines = content.split('\n')
                    if len(lines) > max_lines:
                        content = '\n'.join(lines[:max_lines])
                        content += f'\n\n[... {filename} truncated to {max_lines} lines ...]'

                sections.append(content)

            except Exception as e:
                logger.warning("Failed to load knowledge file", file=filename, error=str(e))
                continue

        combined = "\n\n---\n\n".join(sections) if sections else ""
        self._knowledge_core_content = combined
        return combined

    def get_knowledge_base(self) -> str:
        """Get combined knowledge base content (cached after first load)."""
        return self._load_knowledge_base()

    def reload_knowledge_base(self) -> str:
        """Reload all knowledge base files (useful after editing).

        Clears the cache and reloads from disk.

        Returns:
            Updated combined knowledge content
        """
        return self._load_knowledge_base(force_reload=True)

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
            PosixPath('/path/to/project/.clarity/memory.md')

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
            path: Path to create file (default: ./.clarity/memory.md)

        Returns:
            Path to created file

        Raises:
            FileExistsError: If file already exists

        Example:
            >>> manager.init_project_memory()
            PosixPath('/path/to/project/.clarity/memory.md')

            >>> # Reload to include the new template
            >>> manager.reload_file_memories()
        """
        created_path = self.file_loader.init_project_memory(path)

        # Auto-reload to include the new template
        # If custom path provided, reload from its parent's parent directory
        # (to find the .clarity directory)
        if path:
            # path is like: /some/dir/.clarity/memory.md
            # We want to search from /some/dir
            search_dir = created_path.parent.parent
            self.reload_file_memories(starting_dir=search_dir)
        else:
            self.reload_file_memories()

        return created_path

    def needs_compaction(self, threshold: float = 0.85) -> bool:
        """
        Check if context usage exceeds threshold and compaction is needed.

        Called by orchestrator to decide whether to trigger compaction with user notification.

        Args:
            threshold: Trigger compaction when usage exceeds this fraction (default: 85%)
                       Must be between 0.0 and 1.0 (exclusive)

        Returns:
            True if compaction is recommended
        """
        # Validate threshold bounds
        if not 0.0 < threshold < 1.0:
            raise ValueError(f"threshold must be between 0 and 1, got {threshold}")

        current = (
            self.working_memory.get_current_token_count()
            + self.episodic_memory.current_token_count
        )
        available = self.total_context_tokens - self.system_prompt_tokens

        # Guard against division by zero or negative available space
        if available <= 0:
            return False  # No usable space to manage, don't trigger compaction

        return current > (available * threshold)

    def optimize_context(self, target_tokens: Optional[int] = None) -> int:
        """
        Optimize context to fit within target token budget.

        Called by orchestrator when needs_compaction() returns True.

        Args:
            target_tokens: Target token count (uses total_context_tokens if not provided)

        Returns:
            Number of messages removed from working memory (for user notification)
        """
        target = target_tokens or (
            self.total_context_tokens - self.system_prompt_tokens
        )
        current = (
            self.working_memory.get_current_token_count()
            + self.episodic_memory.current_token_count
        )

        messages_removed = 0

        if current > target:
            # First, compress episodic memory
            self.episodic_memory._compress_old_turns()

            # If still over, compact working memory
            current = (
                self.working_memory.get_current_token_count()
                + self.episodic_memory.current_token_count
            )
            if current > target:
                messages_removed = self.working_memory.compact()

        return messages_removed

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
