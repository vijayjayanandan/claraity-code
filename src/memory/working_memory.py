"""Working Memory - Immediate context for current task."""

import tiktoken
from typing import List, Optional, Dict, Any, TYPE_CHECKING
from datetime import datetime

from .models import Message, CodeContext, TaskContext, MessageRole

if TYPE_CHECKING:
    from src.observability.transcript_logger import TranscriptLogger
    from src.memory.compaction.summarizer import PrioritizedSummarizer

# Use structlog-based logger from observability module
from src.observability import get_logger
logger = get_logger(__name__)


class WorkingMemory:
    """
    Working memory holds the immediate context for the current task.
    Optimized for small context windows with aggressive prioritization.

    Enhanced with:
    - Conversation compaction with prioritized summarization
    - Tool message grouping (assistant+tool_calls evicted with their results)
    - Pending continuation summary for injection into next user turn
    """

    def __init__(
        self,
        max_tokens: int = 2000,
        encoding_name: str = "cl100k_base",
        transcript_logger: Optional["TranscriptLogger"] = None,
    ):
        """
        Initialize working memory.

        Args:
            max_tokens: Maximum token budget for working memory
            encoding_name: Tokenizer encoding name
            transcript_logger: Optional transcript logger for compaction events
        """
        self.max_tokens = max_tokens
        self.encoding = tiktoken.get_encoding(encoding_name)
        self.transcript_logger = transcript_logger

        # Current context
        self.messages: List[Message] = []
        self.task_context: Optional[TaskContext] = None
        self.code_contexts: List[CodeContext] = []
        self.metadata: Dict[str, Any] = {}

        # Compaction state
        self.pending_continuation_summary: Optional[str] = None
        self._summarizer: Optional["PrioritizedSummarizer"] = None

    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        return len(self.encoding.encode(text))

    def get_current_token_count(self) -> int:
        """Get total tokens in working memory."""
        total = 0

        # Count message tokens
        for msg in self.messages:
            if msg.token_count is None:
                msg.token_count = self.count_tokens(msg.content)
            total += msg.token_count

        # Count task context
        if self.task_context:
            total += self.count_tokens(self.task_context.description)

        # Count code contexts
        for ctx in self.code_contexts:
            if ctx.summary:
                total += self.count_tokens(ctx.summary)
            elif ctx.content:
                total += self.count_tokens(ctx.content[:500])  # Truncate if no summary

        return total

    def add_message(self, role: MessageRole, content: str, metadata: Optional[Dict] = None) -> None:
        """
        Add a message to working memory.

        Args:
            role: Message role
            content: Message content
            metadata: Optional metadata
        """
        message = Message(
            role=role,
            content=content,
            timestamp=datetime.now(),
            metadata=metadata or {},
            token_count=self.count_tokens(content),
        )
        self.messages.append(message)
        # NOTE: No auto-compaction here. Orchestrator is responsible for calling
        # compact() when context threshold is reached. This ensures user is notified.

    def add_code_context(self, code_context: CodeContext) -> None:
        """Add code context to working memory."""
        self.code_contexts.append(code_context)
        # NOTE: No auto-compaction here. Orchestrator is responsible for calling
        # compact() when context threshold is reached. This ensures user is notified.

    def set_task_context(self, task_context: TaskContext) -> None:
        """Set current task context."""
        self.task_context = task_context

    def compact(self, use_llm: bool = False) -> int:
        """
        Compact working memory by evicting old messages and generating a summary.

        Uses prioritized summarization to preserve:
        - ALL user messages
        - Key code snippets
        - Errors and fixes
        - Current state

        The summary is stored in `pending_continuation_summary` for injection
        into the next user turn via ContextInjector.

        Args:
            use_llm: Whether to use LLM for summarization (default False)

        Returns:
            Number of messages evicted
        """
        original_count = len(self.messages)
        original_tokens = self.get_current_token_count()

        if original_count <= 2:  # Keep at least last user-assistant pair
            return 0

        # Always keep system messages and last 2 messages
        system_messages = [m for m in self.messages if m.role == MessageRole.SYSTEM]
        recent_messages = self.messages[-2:]

        # Get messages eligible for eviction (excluding system and recent)
        eviction_candidates = [
            m for m in self.messages[:-2] if m.role != MessageRole.SYSTEM
        ]

        # Group tool messages with their assistant messages
        # This ensures we don't orphan tool results from their calls
        eviction_groups = self._group_tool_messages(eviction_candidates)

        # Evict oldest groups until under budget (keep more recent)
        retained_groups: List[List[Message]] = []
        evicted_messages: List[Message] = []

        for group in reversed(eviction_groups):  # Newest first
            # Calculate tokens if we kept this group
            flat_retained = [m for g in retained_groups for m in g]
            test_messages = system_messages + flat_retained + group + recent_messages
            test_tokens = sum(
                m.token_count or self.count_tokens(m.content) for m in test_messages
            )

            if test_tokens <= self.max_tokens * 0.9:  # Keep 10% buffer
                retained_groups.append(group)
            else:
                evicted_messages.extend(group)

        # Generate summary from evicted messages
        if evicted_messages:
            evicted_dicts = [self._message_to_dict(m) for m in evicted_messages]

            # Get or create summarizer
            if self._summarizer is None:
                from src.memory.compaction.summarizer import PrioritizedSummarizer
                self._summarizer = PrioritizedSummarizer(token_budget=6000)

            summary = self._summarizer.generate_summary(evicted_dicts, use_llm=use_llm)
            summary_tokens = self._summarizer.count_tokens(summary)

            # Merge with existing pending summary if present
            if self.pending_continuation_summary:
                # Append new summary to existing
                self.pending_continuation_summary = (
                    self.pending_continuation_summary +
                    "\n\n---\n\n[Additional context from further compaction:]\n\n" +
                    summary
                )
                logger.info(
                    "compaction_merged",
                    evicted_count=len(evicted_messages),
                    summary_tokens=summary_tokens
                )
            else:
                self.pending_continuation_summary = summary

            # Log compaction event to transcript
            if self.transcript_logger:
                try:
                    self.transcript_logger.log_compaction(
                        tokens_before=original_tokens,
                        tokens_after=self.get_current_token_count(),
                        evicted_count=len(evicted_messages),
                        summary_tokens=summary_tokens,
                        summary_preview=summary[:500]
                    )
                except Exception as e:
                    logger.warning("compaction_log_failed", error=str(e))

            logger.info(
                "compaction_complete",
                evicted_count=len(evicted_messages),
                tokens_before=original_tokens,
                summary_tokens=summary_tokens
            )

        # Rebuild messages list
        flat_retained = [m for g in retained_groups for m in g]
        self.messages = sorted(
            system_messages + flat_retained + recent_messages,
            key=lambda m: m.timestamp
        )

        return original_count - len(self.messages)

    def _group_tool_messages(self, messages: List[Message]) -> List[List[Message]]:
        """
        Group messages so tool calls and results stay together.

        This ensures that when evicting messages, we don't orphan tool results
        from their corresponding assistant tool_calls (which would break the
        OpenAI API message format).

        Returns:
            List of groups, where each group is either:
            - [assistant_with_tool_calls, tool_result_1, tool_result_2, ...]
            - [standalone_message]
        """
        groups: List[List[Message]] = []
        current_group: List[Message] = []

        for msg in messages:
            if msg.role == MessageRole.ASSISTANT and msg.metadata.get("tool_calls"):
                # Start new group with assistant tool_calls
                if current_group:
                    groups.append(current_group)
                current_group = [msg]
            elif msg.role == MessageRole.TOOL:
                # Add tool result to current group
                if current_group:
                    current_group.append(msg)
                else:
                    # Orphaned tool message - shouldn't happen but handle gracefully
                    groups.append([msg])
            else:
                # Standalone message (user, assistant without tools)
                if current_group:
                    groups.append(current_group)
                groups.append([msg])
                current_group = []

        if current_group:
            groups.append(current_group)

        return groups

    def _message_to_dict(self, msg: Message) -> Dict[str, Any]:
        """Convert Message to dict format for summarizer."""
        result = {
            "role": msg.role.value,
            "content": msg.content,
        }
        if msg.metadata:
            if msg.metadata.get("tool_calls"):
                result["tool_calls"] = msg.metadata["tool_calls"]
            if msg.metadata.get("tool_call_id"):
                result["tool_call_id"] = msg.metadata["tool_call_id"]
            if msg.metadata.get("name"):
                result["name"] = msg.metadata["name"]
        return result

    def has_pending_summary(self) -> bool:
        """Check if there's a pending continuation summary."""
        return self.pending_continuation_summary is not None

    def consume_pending_summary(self) -> Optional[str]:
        """
        Get and clear the pending continuation summary (one-shot).

        Returns:
            The pending summary, or None if no summary pending
        """
        summary = self.pending_continuation_summary
        self.pending_continuation_summary = None
        return summary

    def get_context_for_llm(self) -> List[Dict[str, Any]]:
        """
        Get formatted context for LLM consumption.

        Properly formats tool messages and assistant messages with tool_calls
        to maintain OpenAI-compatible message format for context retention.

        Returns:
            List of message dictionaries in OpenAI format
        """
        context = []

        # Add task context if available
        if self.task_context:
            task_msg = f"Current Task: {self.task_context.description}"
            if self.task_context.key_concepts:
                task_msg += f"\nKey Concepts: {', '.join(self.task_context.key_concepts)}"
            if self.task_context.constraints:
                task_msg += f"\nConstraints: {', '.join(self.task_context.constraints)}"

            context.append({"role": "system", "content": task_msg})

        # Add code context summaries
        if self.code_contexts:
            code_summary = "Relevant Code:\n"
            for ctx in self.code_contexts:
                code_summary += f"- {ctx.file_path}"
                if ctx.summary:
                    code_summary += f": {ctx.summary}"
                code_summary += "\n"

            context.append({"role": "system", "content": code_summary.strip()})

        # Add messages with proper formatting for tool messages
        for msg in self.messages:
            if msg.role == MessageRole.TOOL:
                # Tool messages need special format for OpenAI API
                tool_msg = {
                    "role": "tool",
                    "content": msg.content,
                    "tool_call_id": msg.metadata.get("tool_call_id", ""),
                }
                # Include name if available (required by some backends)
                if msg.metadata.get("name"):
                    tool_msg["name"] = msg.metadata.get("name")
                context.append(tool_msg)
            elif msg.role == MessageRole.ASSISTANT and msg.metadata.get("tool_calls"):
                # Assistant messages with tool_calls need to include them
                context.append({
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": msg.metadata.get("tool_calls")
                })
            else:
                # Standard messages (user, system, assistant without tools)
                context.append({"role": msg.role.value, "content": msg.content})

        return context

    def clear(self) -> None:
        """Clear all working memory."""
        self.messages.clear()
        self.code_contexts.clear()
        self.task_context = None
        self.metadata.clear()

    def get_summary(self) -> str:
        """Get summary of current working memory."""
        summary_parts = []

        if self.task_context:
            summary_parts.append(f"Task: {self.task_context.description}")

        summary_parts.append(f"Messages: {len(self.messages)}")
        summary_parts.append(f"Code Contexts: {len(self.code_contexts)}")
        summary_parts.append(
            f"Tokens: {self.get_current_token_count()}/{self.max_tokens}"
        )

        return " | ".join(summary_parts)

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize working memory to dictionary.

        Returns:
            Dictionary with all working memory state
        """
        return {
            "messages": [msg.model_dump(mode='json') for msg in self.messages],
            "task_context": self.task_context.model_dump(mode='json') if self.task_context else None,
            "code_contexts": [ctx.model_dump(mode='json') for ctx in self.code_contexts],
            "metadata": self.metadata,
            "max_tokens": self.max_tokens,
        }

    def from_dict(self, data: Dict[str, Any]) -> None:
        """
        Restore working memory from dictionary.

        Args:
            data: Dictionary with working memory state
        """
        from .models import Message, MessageRole, CodeContext, TaskContext

        # Restore messages
        self.messages = [Message.model_validate(msg) for msg in data.get("messages", [])]

        # Restore task context
        task_data = data.get("task_context")
        self.task_context = TaskContext.model_validate(task_data) if task_data else None

        # Restore code contexts
        self.code_contexts = [
            CodeContext.model_validate(ctx) for ctx in data.get("code_contexts", [])
        ]

        # Restore metadata
        self.metadata = data.get("metadata", {})

        # Update max_tokens if present
        if "max_tokens" in data:
            self.max_tokens = data["max_tokens"]
