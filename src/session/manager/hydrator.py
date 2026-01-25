"""Session Hydrator - Rebuilds agent context from JSONL session.

Provides clean session resume by:
1. Loading JSONL into MessageStore
2. Extracting LLM-ready conversation context
3. Restoring agent runtime state (todos, etc.)

Usage:
    from src.session.manager.hydrator import SessionHydrator, HydrationResult

    hydrator = SessionHydrator()
    result = hydrator.hydrate(Path(".sessions/abc123/session.jsonl"))

    # result.store - MessageStore with all messages
    # result.base_llm_messages - OpenAI-format messages for LLM context
    # result.agent_state - Restored agent state (todos, etc.)
    # result.report - Human-readable summary
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple, Set

from src.observability import get_logger
from src.session.persistence.parser import load_session
from src.session.store.memory_store import MessageStore

logger = get_logger("session.hydrator")

# Default max messages for LLM context (can be overridden via env)
DEFAULT_MAX_CONTEXT_MESSAGES = int(os.getenv("SESSION_MAX_CONTEXT_MESSAGES", "100"))


@dataclass
class AgentState:
    """Restored agent runtime state."""
    todos: List[Dict[str, Any]] = field(default_factory=list)
    current_todo_id: Optional[str] = None
    last_stop_reason: Optional[str] = None

    @property
    def has_todos(self) -> bool:
        return len(self.todos) > 0


@dataclass
class HydrationReport:
    """Summary of hydration results."""
    session_id: str
    total_messages: int
    context_messages: int
    has_compaction: bool
    compaction_boundary_seq: Optional[int]
    agent_state_restored: bool
    errors: List[str] = field(default_factory=list)

    def __str__(self) -> str:
        lines = [
            f"Session: {self.session_id}",
            f"Total messages: {self.total_messages}",
            f"Context messages: {self.context_messages}",
            f"Has compaction: {self.has_compaction}",
        ]
        if self.has_compaction:
            lines.append(f"Compaction boundary: seq {self.compaction_boundary_seq}")
        lines.append(f"Agent state restored: {self.agent_state_restored}")
        if self.errors:
            lines.append(f"Errors: {', '.join(self.errors)}")
        return "\n".join(lines)


@dataclass
class HydrationResult:
    """Complete result of session hydration."""
    store: MessageStore
    base_llm_messages: List[Dict[str, Any]]
    agent_state: AgentState
    report: HydrationReport


class SessionHydrator:
    """
    Hydrates agent context from a JSONL session file.

    Responsibilities:
    - Load JSONL into MessageStore (handles streaming collapse, compaction)
    - Extract LLM-ready context via store.get_llm_context()
    - Find and restore agent_state events
    """

    def __init__(self, max_context_messages: Optional[int] = None):
        """
        Initialize hydrator.

        Args:
            max_context_messages: Max messages for LLM context.
                                  Defaults to SESSION_MAX_CONTEXT_MESSAGES env or 100.
        """
        self.max_context_messages = max_context_messages or DEFAULT_MAX_CONTEXT_MESSAGES

    def hydrate(
        self,
        jsonl_path: Path,
        on_progress: Optional[callable] = None
    ) -> HydrationResult:
        """
        Hydrate session from JSONL file.

        Args:
            jsonl_path: Path to session.jsonl file
            on_progress: Optional callback(current, total) for progress

        Returns:
            HydrationResult with store, context, state, and report

        Raises:
            FileNotFoundError: If JSONL file doesn't exist
            ValueError: If JSONL is malformed
        """
        if not jsonl_path.exists():
            raise FileNotFoundError(f"Session file not found: {jsonl_path}")

        errors: List[str] = []

        # Extract session_id from path
        # Supports both: .sessions/abc123/session.jsonl and .sessions/abc123.jsonl
        if jsonl_path.name == "session.jsonl":
            session_id = jsonl_path.parent.name
        else:
            session_id = jsonl_path.stem

        logger.info(f"Hydrating session: {session_id}")

        # 1. Load JSONL into MessageStore
        store = MessageStore()

        try:
            load_session(jsonl_path, store, on_progress)
        except Exception as e:
            errors.append(f"Load error: {e}")
            logger.error(f"Failed to load session: {e}")

        # 2. Extract LLM-ready context
        base_llm_messages = store.get_llm_context(max_messages=self.max_context_messages)

        # 2b. Validate tool call sequences (Claude API requires matching tool_result for each tool_use)
        base_llm_messages, truncation_warning = self._validate_tool_sequences(base_llm_messages)
        if truncation_warning:
            errors.append(truncation_warning)
            logger.warning(truncation_warning)

        # 3. Find and restore agent_state
        agent_state = self._extract_agent_state(store)
        agent_state_restored = agent_state.has_todos or agent_state.last_stop_reason is not None

        # 4. Build report
        report = HydrationReport(
            session_id=session_id,
            total_messages=store.message_count,
            context_messages=len(base_llm_messages),
            has_compaction=store._last_compact_boundary_seq is not None,
            compaction_boundary_seq=store._last_compact_boundary_seq,
            agent_state_restored=agent_state_restored,
            errors=errors
        )

        logger.info(f"Hydration complete: {report.context_messages} context messages, "
                   f"agent_state_restored={agent_state_restored}")

        return HydrationResult(
            store=store,
            base_llm_messages=base_llm_messages,
            agent_state=agent_state,
            report=report
        )

    def _extract_agent_state(self, store: MessageStore) -> AgentState:
        """
        Extract the most recent agent_state from store.

        Looks for system messages with meta.event_type="agent_state".
        Returns the last one found (most recent state).
        """
        agent_state = AgentState()

        # Iterate through all messages looking for agent_state events
        # We want the LAST one (most recent)
        for msg in store.get_ordered_messages():
            if msg.role != "system":
                continue

            meta = msg.meta
            if not meta:
                continue

            # Check for agent_state event type
            event_type = getattr(meta, 'event_type', None)
            if event_type != "agent_state":
                continue

            # Extract state from meta.extra
            extra = getattr(meta, 'extra', None) or {}

            if 'todos' in extra:
                agent_state.todos = extra['todos']
            if 'current_todo_id' in extra:
                agent_state.current_todo_id = extra['current_todo_id']
            if 'last_stop_reason' in extra:
                agent_state.last_stop_reason = extra['last_stop_reason']

        return agent_state

    def _validate_tool_sequences(
        self, messages: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """
        Validate that all tool_use blocks have corresponding tool_result blocks.

        The Claude API requires that every tool_use from an assistant message
        is followed by a tool_result in the next user/tool message. If a session
        was interrupted mid-tool-execution, we need to truncate to a valid point.

        Args:
            messages: List of OpenAI-format messages

        Returns:
            Tuple of (validated_messages, warning_message_or_none)
        """
        if not messages:
            return messages, None

        # Track tool_use IDs and their positions
        pending_tool_ids: Set[str] = set()
        last_valid_index = -1  # Index of last message with complete tool sequences

        for i, msg in enumerate(messages):
            role = msg.get("role")
            content = msg.get("content")

            if role == "assistant":
                # Extract tool_use IDs from assistant message (checks both OpenAI and Anthropic formats)
                tool_use_ids = self._extract_tool_use_ids(msg)
                if tool_use_ids:
                    # New tool calls - add to pending
                    pending_tool_ids.update(tool_use_ids)
                else:
                    # Assistant message without tool calls - valid boundary if no pending
                    if not pending_tool_ids:
                        last_valid_index = i

            elif role == "user":
                # User messages may contain tool_result blocks
                result_ids = self._extract_tool_result_ids(content)
                pending_tool_ids -= result_ids

                # If all pending are resolved, this is a valid boundary
                if not pending_tool_ids:
                    last_valid_index = i

            elif role == "tool":
                # Standalone tool result (OpenAI format)
                tool_call_id = msg.get("tool_call_id")
                if tool_call_id:
                    pending_tool_ids.discard(tool_call_id)
                    if not pending_tool_ids:
                        last_valid_index = i

        # Check if we have incomplete tool sequences
        if pending_tool_ids:
            warning = (
                f"Truncating context: {len(pending_tool_ids)} incomplete tool call(s) "
                f"found without tool_result. Truncating to last valid message."
            )
            logger.info(f"Pending tool IDs: {list(pending_tool_ids)[:5]}...")  # Log first 5

            if last_valid_index >= 0:
                return messages[:last_valid_index + 1], warning
            else:
                # No valid boundary found - return empty to avoid API error
                logger.warning("No valid tool sequence boundary found, returning empty context")
                return [], warning + " No valid boundary found."

        return messages, None

    def _extract_tool_use_ids(self, msg: Dict[str, Any]) -> Set[str]:
        """Extract tool_use IDs from message (handles both OpenAI and Anthropic formats).

        OpenAI format: tool_calls array at message level
        Anthropic format: tool_use blocks in content array

        Args:
            msg: Full message dict (not just content)

        Returns:
            Set of tool_call IDs found in the message
        """
        tool_ids: Set[str] = set()

        # OpenAI format: tool_calls array at message level
        tool_calls = msg.get("tool_calls", [])
        if tool_calls:
            for tc in tool_calls:
                if isinstance(tc, dict):
                    tool_id = tc.get("id")
                    if tool_id:
                        tool_ids.add(tool_id)

        # Anthropic format: tool_use blocks in content array
        content = msg.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "tool_use":
                        tool_id = part.get("id")
                        if tool_id:
                            tool_ids.add(tool_id)
        elif isinstance(content, dict):
            # Single tool use
            if content.get("type") == "tool_use":
                tool_id = content.get("id")
                if tool_id:
                    tool_ids.add(tool_id)

        return tool_ids

    def _extract_tool_result_ids(self, content: Any) -> Set[str]:
        """Extract tool_result IDs from message content (handles various formats)."""
        result_ids: Set[str] = set()

        if isinstance(content, list):
            # Multi-part content (Anthropic format)
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "tool_result":
                        tool_use_id = part.get("tool_use_id")
                        if tool_use_id:
                            result_ids.add(tool_use_id)
        elif isinstance(content, dict):
            # Single tool result
            if content.get("type") == "tool_result":
                tool_use_id = content.get("tool_use_id")
                if tool_use_id:
                    result_ids.add(tool_use_id)

        return result_ids
