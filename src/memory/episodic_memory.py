"""Episodic Memory - Session-scoped conversation history with compression."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import tiktoken

from .models import ConversationTurn, MemoryEntry, MemoryType, Message


class EpisodicMemory:
    """
    Episodic memory stores conversation history for the current session.
    Implements automatic summarization and importance-based retention.
    """

    def __init__(
        self,
        max_tokens: int = 10000,
        compression_threshold: float = 0.8,
        encoding_name: str = "cl100k_base",
    ):
        """
        Initialize episodic memory.

        Args:
            max_tokens: Maximum token budget for episodic memory
            compression_threshold: Trigger compression when this % full (0.0-1.0)
            encoding_name: Tokenizer encoding name
        """
        self.max_tokens = max_tokens
        self.compression_threshold = compression_threshold
        self.encoding = tiktoken.get_encoding(encoding_name)

        self.conversation_turns: list[ConversationTurn] = []
        self.compressed_history: list[str] = []  # Summaries of old conversations
        self.current_token_count = 0

    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        return len(self.encoding.encode(text))

    def add_turn(self, turn: ConversationTurn) -> None:
        """
        Add a conversation turn to episodic memory.

        Args:
            turn: ConversationTurn to add
        """
        # Calculate token count if not set
        if turn.token_count is None:
            user_tokens = self.count_tokens(turn.user_message.content)
            assistant_tokens = self.count_tokens(turn.assistant_message.content)
            turn.token_count = user_tokens + assistant_tokens

        self.conversation_turns.append(turn)
        self.current_token_count += turn.token_count

        # Check if compression is needed
        if self.current_token_count > self.max_tokens * self.compression_threshold:
            self._compress_old_turns()

    def _compress_old_turns(self) -> None:
        """
        Compress old conversation turns to free up token budget.
        Keep recent turns intact, summarize older ones.
        """
        if len(self.conversation_turns) <= 3:  # Keep at least 3 recent turns
            return

        # Keep last 3 turns, compress the rest
        recent_turns = self.conversation_turns[-3:]
        old_turns = self.conversation_turns[:-3]

        # Create summary of old turns
        if old_turns:
            summary = self._create_summary(old_turns)
            self.compressed_history.append(summary)

        # Update state
        self.conversation_turns = recent_turns
        self.current_token_count = sum(t.token_count or 0 for t in self.conversation_turns)

        # Add token count for compressed summaries
        for summary in self.compressed_history:
            self.current_token_count += self.count_tokens(summary)

    def _create_summary(self, turns: list[ConversationTurn]) -> str:
        """
        Create a compressed summary of conversation turns.

        Args:
            turns: list of turns to summarize

        Returns:
            Compressed summary string
        """
        summaries = []

        for turn in turns:
            if turn.summary:
                summaries.append(turn.summary)
            else:
                # Create basic summary
                user_preview = turn.user_message.content[:80]
                assistant_preview = turn.assistant_message.content[:80]

                summary = f"User: {user_preview}... | Assistant: {assistant_preview}..."
                if turn.tool_calls:
                    summary += f" [Used {len(turn.tool_calls)} tools]"

                summaries.append(summary)

        timestamp_range = (
            f"{turns[0].timestamp.strftime('%H:%M')} - {turns[-1].timestamp.strftime('%H:%M')}"
        )
        return f"[{timestamp_range}] " + " | ".join(summaries)

    def get_recent_turns(self, n: int = 5) -> list[ConversationTurn]:
        """
        Get the N most recent conversation turns.

        Args:
            n: Number of recent turns to retrieve

        Returns:
            list of recent turns
        """
        return self.conversation_turns[-n:]

    def get_context_summary(self) -> str:
        """
        Get a summary of the conversation context.

        Returns:
            Context summary string
        """
        parts = []

        # Add compressed history
        if self.compressed_history:
            parts.append("Earlier conversation:")
            parts.extend(self.compressed_history)
            parts.append("")

        # Add recent turns
        if self.conversation_turns:
            parts.append("Recent conversation:")
            for turn in self.conversation_turns:
                parts.append(turn.compress())

        return "\n".join(parts)

    def search_history(self, query: str, max_results: int = 3) -> list[ConversationTurn]:
        """
        Search conversation history for relevant turns.

        Args:
            query: Search query
            max_results: Maximum number of results

        Returns:
            list of relevant conversation turns
        """
        query_lower = query.lower()
        scored_turns = []

        for turn in self.conversation_turns:
            score = 0.0

            # Check user message
            if query_lower in turn.user_message.content.lower():
                score += 1.0

            # Check assistant message
            if query_lower in turn.assistant_message.content.lower():
                score += 0.8

            # Check tool calls
            for tool_call in turn.tool_calls:
                if query_lower in str(tool_call).lower():
                    score += 0.5

            if score > 0:
                scored_turns.append((score, turn))

        # Sort by score and return top results
        scored_turns.sort(key=lambda x: x[0], reverse=True)
        return [turn for _, turn in scored_turns[:max_results]]

    def save_session(self, filepath: Path) -> None:
        """
        Save session to disk.

        Args:
            filepath: Path to save session
        """
        session_data = {
            "compressed_history": self.compressed_history,
            "conversation_turns": [
                {
                    "id": turn.id,
                    "user_message": {
                        "role": turn.user_message.role.value,
                        "content": turn.user_message.content,
                        "timestamp": turn.user_message.timestamp.isoformat(),
                        "metadata": turn.user_message.metadata,
                    },
                    "assistant_message": {
                        "role": turn.assistant_message.role.value,
                        "content": turn.assistant_message.content,
                        "timestamp": turn.assistant_message.timestamp.isoformat(),
                        "metadata": turn.assistant_message.metadata,
                    },
                    "tool_calls": turn.tool_calls,
                    "timestamp": turn.timestamp.isoformat(),
                    "summary": turn.summary,
                    "token_count": turn.token_count,
                }
                for turn in self.conversation_turns
            ],
        }

        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w") as f:
            json.dump(session_data, f, indent=2)

    def load_session(self, filepath: Path) -> None:
        """
        Load session from disk.

        Args:
            filepath: Path to load session from
        """
        with open(filepath) as f:
            session_data = json.load(f)

        self.compressed_history = session_data["compressed_history"]

        # Reconstruct conversation turns
        self.conversation_turns = []
        for turn_data in session_data["conversation_turns"]:
            user_msg = Message(
                role=turn_data["user_message"]["role"],
                content=turn_data["user_message"]["content"],
                timestamp=datetime.fromisoformat(turn_data["user_message"]["timestamp"]),
                metadata=turn_data["user_message"]["metadata"],
            )

            assistant_msg = Message(
                role=turn_data["assistant_message"]["role"],
                content=turn_data["assistant_message"]["content"],
                timestamp=datetime.fromisoformat(turn_data["assistant_message"]["timestamp"]),
                metadata=turn_data["assistant_message"]["metadata"],
            )

            turn = ConversationTurn(
                id=turn_data["id"],
                user_message=user_msg,
                assistant_message=assistant_msg,
                tool_calls=turn_data["tool_calls"],
                timestamp=datetime.fromisoformat(turn_data["timestamp"]),
                summary=turn_data.get("summary"),
                token_count=turn_data.get("token_count"),
            )

            self.conversation_turns.append(turn)

        # Recalculate token count
        self._recalculate_tokens()

    def _recalculate_tokens(self) -> None:
        """Recalculate total token count."""
        self.current_token_count = 0

        for turn in self.conversation_turns:
            if turn.token_count is None:
                user_tokens = self.count_tokens(turn.user_message.content)
                assistant_tokens = self.count_tokens(turn.assistant_message.content)
                turn.token_count = user_tokens + assistant_tokens
            self.current_token_count += turn.token_count

        for summary in self.compressed_history:
            self.current_token_count += self.count_tokens(summary)

    def get_statistics(self) -> dict[str, Any]:
        """Get memory statistics."""
        return {
            "total_turns": len(self.conversation_turns),
            "compressed_chunks": len(self.compressed_history),
            "current_tokens": self.current_token_count,
            "max_tokens": self.max_tokens,
            "utilization": self.current_token_count / self.max_tokens,
            "oldest_turn": (
                self.conversation_turns[0].timestamp.isoformat()
                if self.conversation_turns
                else None
            ),
            "newest_turn": (
                self.conversation_turns[-1].timestamp.isoformat()
                if self.conversation_turns
                else None
            ),
        }

    def clear(self) -> None:
        """Clear all episodic memory."""
        self.conversation_turns.clear()
        self.compressed_history.clear()
        self.current_token_count = 0
