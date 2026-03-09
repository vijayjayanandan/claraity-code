"""In-memory message store with indexes and projections.

This is a PROJECTION, not a ledger. The JSONL file is the ledger.

Key differences from ledger:
- Assistant messages are collapsed by stream_id (latest wins)
- Projection ordering may differ from JSONL line order after collapse
- Indexes provide O(1) lookups

Features:
- O(1) message lookup by UUID
- Ordering by seq (line number / append order)
- Seq uniqueness assertion (fail fast on collision)
- Assistant message collapsing by stream_id (v2.1)
- Tool result indexing for O(1) linkage
- Compaction-aware projections
- Sidechain tracking
- Reactive subscriptions for UI updates

Per v3.1 Patch 1: Store owns seq authority via next_seq() method.
Per v3.1 Patch 2: _remove_from_indexes() cleans _sidechains as well.
Per v2.1: Collapse by stream_id (not provider_message_id).
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from src.core.events import ToolStatus
from src.observability import get_logger

if TYPE_CHECKING:
    from ..models.message import FileHistorySnapshot, Message

logger = get_logger("session.store")


class StoreEvent(str, Enum):
    """Store event types for subscriptions.

    Event lifecycle for streaming messages:
    - MESSAGE_ADDED: New message added (first appearance of a stream_id)
    - MESSAGE_UPDATED: Existing message updated (collapse by stream_id)
    - MESSAGE_FINALIZED: Stream complete, no more updates expected
    - BULK_LOAD_COMPLETE: Replay finished, all messages loaded
    - TOOL_STATE_UPDATED: Tool execution state changed (ephemeral, not persisted)
    """
    MESSAGE_ADDED = "message_added"
    MESSAGE_UPDATED = "message_updated"
    MESSAGE_FINALIZED = "message_finalized"
    SNAPSHOT_ADDED = "snapshot_added"
    STORE_CLEARED = "store_cleared"
    BULK_LOAD_COMPLETE = "bulk_load_complete"
    TOOL_STATE_UPDATED = "tool_state_updated"


@dataclass
class ToolExecutionState:
    """Ephemeral tool execution state (not persisted to JSONL).

    Tracks the lifecycle of tool execution for UI rendering.
    Agent updates this via MessageStore.update_tool_state().
    TUI reads via MessageStore.get_tool_state() or TOOL_STATE_UPDATED notifications.
    """
    status: ToolStatus = ToolStatus.PENDING
    result: Any | None = None
    error: str | None = None
    duration_ms: int | None = None


@dataclass
class StoreNotification:
    """Notification payload for store events."""
    event: StoreEvent
    message: Optional["Message"] = None
    snapshot: Optional["FileHistorySnapshot"] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # For TOOL_STATE_UPDATED events
    tool_call_id: str | None = None
    tool_state: ToolExecutionState | None = None


Subscriber = Callable[[StoreNotification], None]


class SeqCollisionError(Exception):
    """Raised when two messages have the same seq (invariant violation)."""
    pass


class MessageStore:
    """
    Thread-safe in-memory store for session messages.

    This is a PROJECTION, not a ledger. The JSONL file is the ledger.

    Key differences from ledger:
    - Assistant messages are collapsed by stream_id (latest wins)
    - Projection ordering may differ from JSONL line order after collapse
    - Indexes provide O(1) lookups

    Features:
    - O(1) message lookup by UUID
    - Ordering by seq (line number / append order)
    - seq uniqueness assertion (fail fast on collision)
    - Assistant message collapsing by stream_id (v2.1)
    - Tool result indexing for O(1) linkage
    - Compaction-aware projections
    - Sidechain tracking
    - Reactive subscriptions for UI updates
    """

    def __init__(self):
        # Primary storage
        self._messages: dict[str, Message] = {}

        # Indexes
        self._by_seq: dict[int, str] = {}  # seq -> uuid (unique keys)
        self._children: dict[str, list[str]] = {}  # parent_uuid -> [child_uuids]
        self._root_ids: list[str] = []  # Messages with no parent

        # Assistant message collapse index (stream_id -> uuid)
        self._by_stream_id: dict[str, str] = {}

        # Tool linkage indexes
        self._tool_results: dict[str, str] = {}  # tool_call_id -> tool_result_message_uuid
        self._assistant_tools: dict[str, list[str]] = {}  # assistant_uuid -> [tool_call_ids]
        self._tool_approvals: dict[str, str] = {}  # tool_call_id -> approval_message_uuid

        # Clarify indexes (for interactive clarification flow)
        self._clarify_requests: dict[str, str] = {}   # call_id -> message_uuid
        self._clarify_responses: dict[str, str] = {}  # call_id -> message_uuid

        # Sidechain tracking
        self._sidechains: dict[str, list[str]] = {}  # parent_uuid -> [sidechain_uuids]

        # Compaction tracking
        self._last_compact_boundary_seq: int | None = None
        self._compact_boundary_uuid: str | None = None
        self._compact_summary_uuid: str | None = None

        # File snapshots
        self._snapshots: dict[str, FileHistorySnapshot] = {}

        # Ephemeral tool execution state (NOT persisted)
        # Keyed by tool_call_id, updated by Agent, read by TUI
        self._tool_state: dict[str, ToolExecutionState] = {}

        # Tool metadata (tool_name, args_summary) for hydration after mount
        self._tool_metadata: dict[str, dict[str, Any]] = {}

        # Sequence tracking (Store owns seq authority per v3.1 Patch 1)
        self._max_seq: int = 0

        # Subscriptions
        self._subscribers: set[Subscriber] = set()
        self._lock = threading.RLock()

        # Metadata
        self._session_id: str | None = None
        self._is_bulk_loading: bool = False

        # Permission mode tracking (extracted from permission_mode_changed events)
        self._current_mode: str = "normal"  # Current permission mode
        self._plan_hash: str | None = None  # Plan hash if in plan mode
        self._plan_path: str | None = None  # Plan file path if in plan mode

    # =========================================================================
    # Core Operations
    # =========================================================================

    def add_message(self, message: "Message") -> None:
        """
        Add a message to the store.

        Handles:
        - Seq uniqueness assertion
        - Assistant message collapsing by stream_id
        - Index maintenance
        - Sidechain tracking
        - Compaction boundary detection
        - Tool result indexing

        Emits:
        - MESSAGE_ADDED: First time a message/stream_id is added
        - MESSAGE_UPDATED: When collapsing an existing stream_id

        Raises:
            SeqCollisionError: If seq already exists for different message
        """
        with self._lock:
            uuid = message.uuid
            parent_uuid = message.parent_uuid
            seq = message.seq
            is_update = False  # Track if this is an update vs new message

            # Update max seq
            if seq > self._max_seq:
                self._max_seq = seq

            # Handle assistant message collapsing by stream_id (v2.1)
            if message.is_assistant:
                stream_id = message.get_collapse_key()  # Returns meta.stream_id
                if stream_id and stream_id in self._by_stream_id:
                    # Replace previous entry for this stream - this is an UPDATE
                    is_update = True
                    old_uuid = self._by_stream_id[stream_id]
                    old_seq = self._messages[old_uuid].seq if old_uuid in self._messages else None
                    self._remove_from_indexes(old_uuid)
                    del self._messages[old_uuid]
                    # Free up the old seq slot
                    if old_seq is not None and old_seq in self._by_seq:
                        del self._by_seq[old_seq]

                if stream_id:
                    self._by_stream_id[stream_id] = uuid

                # Index tool calls from this assistant message
                tool_call_ids = message.get_tool_call_ids()
                if tool_call_ids:
                    self._assistant_tools[uuid] = tool_call_ids

            # Handle tool result indexing (role=tool)
            if message.is_tool and message.tool_call_id:
                self._tool_results[message.tool_call_id] = uuid

                # Log tool message addition for debugging
                from src.observability import get_logger
                logger = get_logger("session.store")
                logger.debug(
                    f"[ADD_MESSAGE] Tool message added: tool_call_id={message.tool_call_id}, "
                    f"uuid={uuid}, seq={seq}, is_sidechain={message.is_sidechain}"
                )

                # Fix 4: Validate that tool result has a corresponding assistant tool_call
                # This detects orphaned tool results (JSONL corruption, missing assistant message)
                tool_call_id = message.tool_call_id
                has_assistant = False
                for _assistant_uuid, tool_call_ids in self._assistant_tools.items():
                    if tool_call_id in tool_call_ids:
                        has_assistant = True
                        break

                if not has_assistant:
                    logger.warning(
                        f"Orphaned tool result: tool_call_id={tool_call_id} "
                        f"has no matching assistant tool_call. Message uuid={uuid}"
                    )

            # Handle tool approval indexing (system event with event_type="tool_approval")
            if message.is_system and message.meta.event_type == "tool_approval":
                extra = message.meta.extra or {}
                tool_call_id = extra.get("tool_call_id")
                if tool_call_id:
                    self._tool_approvals[tool_call_id] = uuid

            # Handle clarify_request indexing
            if message.is_system and message.meta.event_type == "clarify_request":
                extra = message.meta.extra or {}
                call_id = extra.get("call_id")
                if call_id:
                    self._clarify_requests[call_id] = uuid

            # Handle clarify_response indexing
            if message.is_system and message.meta.event_type == "clarify_response":
                extra = message.meta.extra or {}
                call_id = extra.get("call_id")
                if call_id:
                    self._clarify_responses[call_id] = uuid

            # Handle permission mode changes
            if message.is_system and message.meta.event_type == "permission_mode_changed":
                extra = message.meta.extra or {}
                new_mode = extra.get("new_mode", "normal")
                self._current_mode = new_mode

            # Handle plan_submitted events (track plan hash and path)
            if message.is_system and message.meta.event_type == "plan_submitted":
                extra = message.meta.extra or {}
                self._plan_hash = extra.get("plan_hash")
                self._plan_path = extra.get("plan_path")

            # Handle compaction boundary
            if message.is_system and message.meta.event_type == "compact_boundary":
                self._last_compact_boundary_seq = seq
                self._compact_boundary_uuid = uuid

            # Handle compact summary
            if message.is_user and message.meta.is_compact_summary:
                self._compact_summary_uuid = uuid

            # Assert seq uniqueness (fail fast on collision)
            if seq in self._by_seq and self._by_seq[seq] != uuid:
                existing_uuid = self._by_seq[seq]
                raise SeqCollisionError(
                    f"Seq collision: seq={seq} already assigned to {existing_uuid}, "
                    f"cannot assign to {uuid}"
                )

            # Store message
            self._messages[uuid] = message
            self._by_seq[seq] = uuid

            # Track parent-child / sidechain relationships
            if parent_uuid is None:
                if uuid not in self._root_ids:
                    self._root_ids.append(uuid)
            else:
                if message.is_sidechain:
                    if parent_uuid not in self._sidechains:
                        self._sidechains[parent_uuid] = []
                    self._sidechains[parent_uuid].append(uuid)
                else:
                    if parent_uuid not in self._children:
                        self._children[parent_uuid] = []
                    if uuid not in self._children[parent_uuid]:
                        self._children[parent_uuid].append(uuid)

            # Set session metadata from first message
            if self._session_id is None:
                self._session_id = message.session_id

            # Notify subscribers with appropriate event type
            if not self._is_bulk_loading:
                event_type = StoreEvent.MESSAGE_UPDATED if is_update else StoreEvent.MESSAGE_ADDED
                self._notify(StoreNotification(
                    event=event_type,
                    message=message,
                    metadata={"is_streaming_update": is_update}
                ))

    def finalize_message(self, stream_id: str) -> Optional["Message"]:
        """
        Mark a streaming message as finalized.

        Call this when a stream completes to emit MESSAGE_FINALIZED.
        The message should already exist in the store via add_message().

        Args:
            stream_id: The stream_id of the message to finalize

        Returns:
            The finalized message, or None if not found

        Emits:
            MESSAGE_FINALIZED with the final message state
        """
        with self._lock:
            uuid = self._by_stream_id.get(stream_id)
            if not uuid:
                logger.warning(f"Cannot finalize: stream_id {stream_id} not found")
                return None

            message = self._messages.get(uuid)
            if not message:
                logger.warning(f"Cannot finalize: message {uuid} not found")
                return None

            # Notify subscribers of finalization
            if not self._is_bulk_loading:
                self._notify(StoreNotification(
                    event=StoreEvent.MESSAGE_FINALIZED,
                    message=message,
                    metadata={"stream_id": stream_id}
                ))

            return message

    def get_message(self, uuid: str) -> Optional["Message"]:
        """Get a message by UUID."""
        with self._lock:
            return self._messages.get(uuid)

    def get_by_seq(self, seq: int) -> Optional["Message"]:
        """Get a message by sequence number."""
        with self._lock:
            uuid = self._by_seq.get(seq)
            return self._messages.get(uuid) if uuid else None

    def next_seq(self) -> int:
        """
        Get next sequence number for runtime appends.

        This is the SINGLE AUTHORITY for seq allocation (v3.1 Patch 1).
        """
        with self._lock:
            self._max_seq += 1
            return self._max_seq

    # =========================================================================
    # Ordering & Iteration
    # =========================================================================

    def get_ordered_messages(self) -> list["Message"]:
        """
        Get all messages ordered by seq.

        Note: This is projection order, not ledger order.
        Collapsed assistant messages use the seq of their latest entry.
        """
        with self._lock:
            seqs = sorted(self._by_seq.keys())
            return [self._messages[self._by_seq[s]] for s in seqs if self._by_seq[s] in self._messages]

    def get_messages_after_seq(self, seq: int) -> list["Message"]:
        """Get messages with seq > given value, ordered."""
        with self._lock:
            seqs = sorted(s for s in self._by_seq.keys() if s > seq)
            return [self._messages[self._by_seq[s]] for s in seqs if self._by_seq[s] in self._messages]

    # =========================================================================
    # Tool Linkage (O(1) lookups)
    # =========================================================================

    def get_tool_result(self, tool_call_id: str) -> Optional["Message"]:
        """Get the tool result message for a tool_call_id. O(1)."""
        with self._lock:
            uuid = self._tool_results.get(tool_call_id)
            return self._messages.get(uuid) if uuid else None

    def get_tool_calls_for_assistant(self, assistant_uuid: str) -> list[str]:
        """Get tool_call_ids requested by an assistant message."""
        with self._lock:
            return self._assistant_tools.get(assistant_uuid, [])

    def get_tool_approval(self, tool_call_id: str) -> Optional["Message"]:
        """Get the tool approval event for a tool_call_id. O(1).

        Returns the system message with event_type="tool_approval" if the user
        made an approval decision for this tool call.

        The approval decision is in meta.extra:
        - tool_call_id: The tool call ID
        - tool_name: Name of the tool
        - approved: bool
        - action: "yes", "yes_all", or "no"
        - feedback: Optional rejection feedback
        """
        with self._lock:
            uuid = self._tool_approvals.get(tool_call_id)
            return self._messages.get(uuid) if uuid else None

    # =========================================================================
    # Clarify Linkage (O(1) lookups)
    # =========================================================================

    def get_clarify_request(self, call_id: str) -> Optional["Message"]:
        """Get clarify request by call_id. O(1).

        Returns the system message with event_type="clarify_request" containing
        the questions that were asked.

        The questions are in meta.extra:
        - call_id: Tool call ID
        - questions: list of question dicts
        - context: Optional context string
        """
        with self._lock:
            uuid = self._clarify_requests.get(call_id)
            return self._messages.get(uuid) if uuid else None

    def get_clarify_response(self, call_id: str) -> Optional["Message"]:
        """Get clarify response by call_id. O(1).

        Returns the system message with event_type="clarify_response" containing
        the user's answers.

        The response is in meta.extra:
        - call_id: Tool call ID
        - submitted: bool
        - responses: dict of question_id -> selected_option_id(s)
        - chat_instead: bool
        - chat_message: str | None
        """
        with self._lock:
            uuid = self._clarify_responses.get(call_id)
            return self._messages.get(uuid) if uuid else None

    def get_pending_clarify_call_ids(self) -> list[str]:
        """Get call_ids with requests but no responses.

        Used during session resume to detect pending clarifications
        that need to be re-displayed to the user.

        Returns:
            list of call_ids that have clarify_request but no clarify_response
        """
        with self._lock:
            pending = []
            for call_id in self._clarify_requests:
                if call_id not in self._clarify_responses:
                    pending.append(call_id)
            return pending

    # =========================================================================
    # Tool Execution State (Ephemeral, NOT persisted)
    # =========================================================================

    def update_tool_state(
        self,
        tool_call_id: str,
        status: ToolStatus,
        result: Any | None = None,
        error: str | None = None,
        duration_ms: int | None = None,
        tool_name: str | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> None:
        """Update ephemeral tool execution state.

        Called by Agent/ToolRunner during tool lifecycle:
        - PENDING: Tool call received
        - AWAITING_APPROVAL: Waiting for user approval
        - RUNNING: Execution in progress
        - SUCCESS/ERROR: Execution complete

        Emits TOOL_STATE_UPDATED notification for TUI rendering.

        Note: This state is NOT persisted to JSONL. It's ephemeral,
        session-scoped, and exists only for live UI updates.
        Tool results are persisted via role="tool" messages.
        """
        with self._lock:
            self._tool_state[tool_call_id] = ToolExecutionState(
                status=status,
                result=result,
                error=error,
                duration_ms=duration_ms
            )

            # Store metadata for hydration (merge, don't overwrite)
            if tool_name or extra_metadata:
                meta = self._tool_metadata.get(tool_call_id, {})
                if extra_metadata:
                    meta.update(extra_metadata)
                if tool_name:
                    meta["tool_name"] = tool_name
                self._tool_metadata[tool_call_id] = meta

            # Cap tool state history to prevent unbounded growth
            MAX_TOOL_STATE_ENTRIES = 1000
            if len(self._tool_state) > MAX_TOOL_STATE_ENTRIES:
                # Remove oldest entries (keep most recent)
                oldest_keys = list(self._tool_state.keys())[:-MAX_TOOL_STATE_ENTRIES]
                for key in oldest_keys:
                    del self._tool_state[key]
                    self._tool_metadata.pop(key, None)

            if not self._is_bulk_loading:
                metadata = dict(extra_metadata) if extra_metadata else {}
                if tool_name:
                    metadata["tool_name"] = tool_name
                self._notify(StoreNotification(
                    event=StoreEvent.TOOL_STATE_UPDATED,
                    tool_call_id=tool_call_id,
                    tool_state=self._tool_state[tool_call_id],
                    metadata=metadata,
                ))

    def get_tool_state(self, tool_call_id: str) -> ToolExecutionState | None:
        """Get ephemeral tool execution state.

        Called by TUI when rendering tool cards.
        Returns None if not found (e.g., during replay when state wasn't set).
        """
        with self._lock:
            return self._tool_state.get(tool_call_id)

    def get_tool_states(self) -> dict[str, ToolExecutionState]:
        """Snapshot of all tool execution states (thread-safe copy)."""
        with self._lock:
            return dict(self._tool_state)

    def get_tool_metadata(self, tool_call_id: str) -> dict[str, Any]:
        """Get metadata for a tool call (tool_name, args_summary, etc.)."""
        with self._lock:
            return dict(self._tool_metadata.get(tool_call_id, {}))

    def get_all_tool_metadata(self) -> dict[str, dict[str, Any]]:
        """Snapshot of all tool metadata (thread-safe copy)."""
        with self._lock:
            return {k: dict(v) for k, v in self._tool_metadata.items()}

    def clear_tool_state(self) -> None:
        """Clear ephemeral tool state (session reset)."""
        with self._lock:
            self._tool_state.clear()
            self._tool_metadata.clear()

    # =========================================================================
    # Sidechain Operations
    # =========================================================================

    def get_mainline_messages(self) -> list["Message"]:
        """Get non-sidechain messages in seq order."""
        with self._lock:
            messages = [m for m in self._messages.values() if not m.is_sidechain]
            return sorted(messages, key=lambda m: m.seq)

    def get_sidechain_count(self, parent_uuid: str) -> int:
        """Get number of alternate responses for a parent."""
        with self._lock:
            return len(self._sidechains.get(parent_uuid, []))

    def get_sidechains(self, parent_uuid: str) -> list["Message"]:
        """Get sidechain messages for a parent."""
        with self._lock:
            uuids = self._sidechains.get(parent_uuid, [])
            return [self._messages[u] for u in uuids if u in self._messages]

    # =========================================================================
    # Projection Views
    # =========================================================================

    def get_transcript_view(self, include_pre_compaction: bool = False) -> list["Message"]:
        """
        Get messages for transcript display.

        Default: Post-compaction messages only (mainline), EXCLUDING boundary marker.
        With flag: Everything including pre-compaction.

        Use get_compact_boundary() separately to render banner.
        """
        with self._lock:
            messages = self.get_mainline_messages()

            if not include_pre_compaction and self._last_compact_boundary_seq is not None:
                # EXCLUSIVE: seq > boundary (not >=)
                # Boundary marker itself is not in the list
                messages = [m for m in messages if m.seq > self._last_compact_boundary_seq]

            return messages

    def get_llm_context(self, max_messages: int | None = None) -> list[dict[str, Any]]:
        """
        Get messages suitable for LLM context (OpenAI format).

        - Post-compaction only (exclusive)
        - Mainline only (no sidechains)
        - Excludes isVisibleInTranscriptOnly
        - Uses to_llm_dict() to strip meta

        Returns:
            list of dicts in OpenAI message format
        """
        from src.observability import get_logger
        logger = get_logger("session.store")

        with self._lock:
            messages = []
            mainline = self.get_mainline_messages()

            # Debug: Count tool messages in mainline
            tool_in_mainline = [m for m in mainline if m.is_tool]
            if tool_in_mainline:
                logger.warning(
                    f"[GET_LLM_CONTEXT] Mainline has {len(tool_in_mainline)} tool messages: "
                    f"{[(m.tool_call_id, m.seq) for m in tool_in_mainline]}"
                )

            for m in mainline:
                # Skip pre-compaction (exclusive)
                if self._last_compact_boundary_seq and m.seq <= self._last_compact_boundary_seq:
                    if m.is_tool:
                        logger.warning(
                            f"[GET_LLM_CONTEXT] Filtered tool message (pre-compaction): "
                            f"tool_call_id={m.tool_call_id}, seq={m.seq}, "
                            f"boundary_seq={self._last_compact_boundary_seq}"
                        )
                    continue

                # Check if should be included in context
                if not m.should_include_in_context:
                    if m.is_tool:
                        logger.warning(
                            f"[GET_LLM_CONTEXT] Filtered tool message (should_include_in_context=False): "
                            f"tool_call_id={m.tool_call_id}, seq={m.seq}"
                        )
                    continue

                messages.append(m)

            if max_messages:
                messages = messages[-max_messages:]

            # Convert to LLM format (strip meta)
            return [m.to_llm_dict() for m in messages]

    def get_llm_context_messages(self, max_messages: int | None = None) -> list["Message"]:
        """
        Get Message objects for LLM context (for custom processing).

        - Post-compaction only (exclusive)
        - Mainline only (no sidechains)
        - Excludes isVisibleInTranscriptOnly
        """
        with self._lock:
            messages = []

            for m in self.get_mainline_messages():
                # Skip pre-compaction (exclusive)
                if self._last_compact_boundary_seq and m.seq <= self._last_compact_boundary_seq:
                    continue

                # Check if should be included in context
                if not m.should_include_in_context:
                    continue

                messages.append(m)

            if max_messages:
                messages = messages[-max_messages:]

            return messages

    def get_compact_summary(self) -> Optional["Message"]:
        """Get the compaction summary message if present."""
        with self._lock:
            if self._compact_summary_uuid:
                return self._messages.get(self._compact_summary_uuid)
            return None

    def get_compact_boundary(self) -> Optional["Message"]:
        """Get the compact boundary marker for banner rendering."""
        with self._lock:
            if self._compact_boundary_uuid:
                return self._messages.get(self._compact_boundary_uuid)
            return None

    def compact(self, summary_content: str, evicted_count: int, pre_tokens: int = 0) -> int:
        """
        Compact conversation by setting a boundary and inserting a summary.

        All prior messages are evicted (excluded from future get_llm_context()
        calls). The summary replaces the entire conversation history, giving
        the LLM a clean continuation point. This matches how Claude Code
        handles compaction.

        Args:
            summary_content: Summary of evicted messages (from PrioritizedSummarizer)
            evicted_count: Number of messages being evicted (for logging/event)
            pre_tokens: Token count before compaction (for logging/meta)

        Returns:
            Number of messages evicted
        """
        from ..models.message import Message

        with self._lock:
            session_id = self._session_id
            if not session_id:
                logger.warning("compact_skipped: no session_id")
                return 0

            # 1. Insert compact_boundary system message.
            #    add_message() detects event_type="compact_boundary" and sets
            #    _last_compact_boundary_seq to this message's seq. Since this
            #    seq is higher than all prior messages, get_llm_context() will
            #    exclude everything before it.
            boundary_msg = Message.create_system(
                content="[Conversation compacted]",
                session_id=session_id,
                seq=self.next_seq(),
                event_type="compact_boundary",
                include_in_llm_context=False,
                pre_tokens=pre_tokens,
            )
            self.add_message(boundary_msg)

            # 2. Insert summary as user message with is_compact_summary flag.
            #    This is the only prior context the LLM will see going forward.
            summary_msg = Message.create_user(
                content=(
                    "[Conversation summary - earlier messages were compacted "
                    "to free context space]\n\n"
                    + summary_content
                ),
                session_id=session_id,
                parent_uuid=None,
                seq=self.next_seq(),
                is_compact_summary=True,
            )
            self.add_message(summary_msg)

            logger.info(
                "compact_complete",
                evicted_count=evicted_count,
                pre_tokens=pre_tokens,
            )

            return evicted_count

    def has_compaction(self) -> bool:
        """Check if session has been compacted."""
        with self._lock:
            return self._last_compact_boundary_seq is not None

    # =========================================================================
    # Threading (Parent-Child)
    # =========================================================================

    def get_children(self, uuid: str) -> list["Message"]:
        """Get direct children of a message (non-sidechain)."""
        with self._lock:
            child_ids = self._children.get(uuid, [])
            return [self._messages[cid] for cid in child_ids if cid in self._messages]

    def get_thread(self, uuid: str) -> list["Message"]:
        """Get message thread from root to given UUID."""
        with self._lock:
            thread = []
            current_uuid = uuid

            while current_uuid:
                message = self._messages.get(current_uuid)
                if message:
                    thread.insert(0, message)
                    current_uuid = message.parent_uuid
                else:
                    break

            return thread

    # =========================================================================
    # Snapshot Operations
    # =========================================================================

    def add_snapshot(self, snapshot: "FileHistorySnapshot") -> None:
        """Add a file history snapshot."""
        with self._lock:
            self._snapshots[snapshot.uuid] = snapshot

            if not self._is_bulk_loading:
                self._notify(StoreNotification(
                    event=StoreEvent.SNAPSHOT_ADDED,
                    snapshot=snapshot
                ))

    def get_snapshot(self, uuid: str) -> Optional["FileHistorySnapshot"]:
        """Get snapshot by UUID."""
        with self._lock:
            return self._snapshots.get(uuid)

    # =========================================================================
    # Bulk Operations
    # =========================================================================

    def begin_bulk_load(self) -> None:
        """Begin bulk loading (suppresses individual notifications)."""
        with self._lock:
            self._is_bulk_loading = True

    def end_bulk_load(self) -> None:
        """End bulk loading and notify subscribers."""
        with self._lock:
            self._is_bulk_loading = False
            self._notify(StoreNotification(
                event=StoreEvent.BULK_LOAD_COMPLETE,
                metadata={"message_count": len(self._messages)}
            ))

    def clear(self) -> None:
        """Clear all messages and indexes."""
        with self._lock:
            self._messages.clear()
            self._by_seq.clear()
            self._children.clear()
            self._root_ids.clear()
            self._by_stream_id.clear()
            self._tool_results.clear()
            self._assistant_tools.clear()
            self._tool_approvals.clear()
            self._clarify_requests.clear()
            self._clarify_responses.clear()
            self._sidechains.clear()
            self._snapshots.clear()
            self._tool_state.clear()  # Clear ephemeral tool state
            self._tool_metadata.clear()  # Clear tool metadata
            self._last_compact_boundary_seq = None
            self._compact_boundary_uuid = None
            self._compact_summary_uuid = None
            self._max_seq = 0
            self._session_id = None
            self._current_mode = "normal"
            self._plan_hash = None
            self._plan_path = None

            self._notify(StoreNotification(event=StoreEvent.STORE_CLEARED))

    # =========================================================================
    # Subscription Management
    # =========================================================================

    def subscribe(self, callback: Subscriber) -> Callable[[], None]:
        """Subscribe to store events. Returns unsubscribe function."""
        with self._lock:
            self._subscribers.add(callback)

        def unsubscribe():
            with self._lock:
                self._subscribers.discard(callback)

        return unsubscribe

    def _notify(self, notification: StoreNotification) -> None:
        """Notify all subscribers."""
        subscribers = list(self._subscribers)
        for callback in subscribers:
            try:
                callback(notification)
            except Exception as e:
                logger.warning(f"Subscriber error: {e}")

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    def _remove_from_indexes(self, uuid: str) -> None:
        """
        Remove a message from ALL indexes.

        Used during assistant message collapse to prevent ghost references.
        Per v3.1 Patch 2: Also cleans _sidechains.
        """
        if uuid not in self._messages:
            return

        message = self._messages[uuid]
        parent_uuid = message.parent_uuid

        # Remove from parent's children list
        if parent_uuid and parent_uuid in self._children:
            self._children[parent_uuid] = [
                cid for cid in self._children[parent_uuid] if cid != uuid
            ]

        # Remove from parent's sidechains list (v3.1 Patch 2)
        if parent_uuid and parent_uuid in self._sidechains:
            self._sidechains[parent_uuid] = [
                sid for sid in self._sidechains[parent_uuid] if sid != uuid
            ]

        # Remove from root list
        if uuid in self._root_ids:
            self._root_ids.remove(uuid)

        # Remove tool use tracking
        if uuid in self._assistant_tools:
            del self._assistant_tools[uuid]

        # Remove from stream_id index
        stream_id = message.get_collapse_key() if message.is_assistant else None
        if stream_id and stream_id in self._by_stream_id:
            if self._by_stream_id[stream_id] == uuid:
                del self._by_stream_id[stream_id]

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def message_count(self) -> int:
        with self._lock:
            return len(self._messages)

    @property
    def is_empty(self) -> bool:
        with self._lock:
            return len(self._messages) == 0

    @property
    def max_seq(self) -> int:
        with self._lock:
            return self._max_seq

    @property
    def current_mode(self) -> str:
        """Get the current permission mode (normal, plan, awaiting_approval, auto)."""
        with self._lock:
            return self._current_mode

    @property
    def plan_hash(self) -> str | None:
        """Get the current plan hash (if in plan mode or awaiting approval)."""
        with self._lock:
            return self._plan_hash

    @property
    def plan_path(self) -> str | None:
        """Get the current plan file path (if in plan mode or awaiting approval)."""
        with self._lock:
            return self._plan_path
