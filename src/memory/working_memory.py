"""Working Memory - Immediate context for current task."""

import tiktoken
from typing import List, Optional, Dict, Any
from datetime import datetime

from .models import Message, CodeContext, TaskContext, MessageRole


class WorkingMemory:
    """
    Working memory holds the immediate context for the current task.
    Optimized for small context windows with aggressive prioritization.
    """

    def __init__(
        self,
        max_tokens: int = 2000,
        encoding_name: str = "cl100k_base",
    ):
        """
        Initialize working memory.

        Args:
            max_tokens: Maximum token budget for working memory
            encoding_name: Tokenizer encoding name
        """
        self.max_tokens = max_tokens
        self.encoding = tiktoken.get_encoding(encoding_name)

        # Current context
        self.messages: List[Message] = []
        self.task_context: Optional[TaskContext] = None
        self.code_contexts: List[CodeContext] = []
        self.metadata: Dict[str, Any] = {}

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

        # Auto-compact if over budget
        if self.get_current_token_count() > self.max_tokens:
            self._compact()

    def add_code_context(self, code_context: CodeContext) -> None:
        """Add code context to working memory."""
        self.code_contexts.append(code_context)

        # Auto-compact if needed
        if self.get_current_token_count() > self.max_tokens:
            self._compact()

    def set_task_context(self, task_context: TaskContext) -> None:
        """Set current task context."""
        self.task_context = task_context

    def _compact(self) -> None:
        """
        Compact working memory by removing or summarizing old messages.
        Uses importance-based retention strategy.
        """
        if len(self.messages) <= 2:  # Keep at least last user-assistant pair
            return

        # Always keep system messages and last 2 messages
        system_messages = [m for m in self.messages if m.role == MessageRole.SYSTEM]
        recent_messages = self.messages[-2:]

        # Score other messages by recency
        other_messages = [
            m for m in self.messages[:-2] if m.role != MessageRole.SYSTEM
        ]

        # Remove oldest messages until under budget
        retained_messages = system_messages.copy()
        for msg in reversed(other_messages):  # Keep more recent messages
            test_messages = retained_messages + [msg] + recent_messages
            test_tokens = sum(
                m.token_count or self.count_tokens(m.content) for m in test_messages
            )

            if test_tokens <= self.max_tokens * 0.9:  # Keep 10% buffer
                retained_messages.append(msg)
            else:
                break

        self.messages = sorted(
            retained_messages + recent_messages, key=lambda m: m.timestamp
        )

    def get_context_for_llm(self) -> List[Dict[str, str]]:
        """
        Get formatted context for LLM consumption.

        Returns:
            List of message dictionaries
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

        # Add messages
        for msg in self.messages:
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
