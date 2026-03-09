"""
ObservationStore - External storage for tool outputs with reversible pointers.

Phase 2 of Context Management v2: Enables masking old tool outputs without
losing recoverability. Full content is stored in SQLite, while context
windows contain lightweight pointers that can be rehydrated on demand.
"""

import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class Importance(Enum):
    """Importance levels for observations."""

    CRITICAL = "critical"  # Never mask unless RED and last resort
    NORMAL = "normal"  # Mask after OBSERVATION_MASK_AGE turns
    LOW = "low"  # Mask first when under pressure


@dataclass
class Observation:
    """Represents a stored tool observation."""

    observation_id: str
    tool_name: str
    args_hash: str
    content: str
    turn_id: int
    importance: Importance
    token_count: int
    created_at: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_pointer(self) -> str:
        """Generate pointer format for this observation."""
        return ObservationPointer.format(
            observation_id=self.observation_id,
            tool_name=self.tool_name,
            token_count=self.token_count,
            importance=self.importance.value,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "observation_id": self.observation_id,
            "tool_name": self.tool_name,
            "args_hash": self.args_hash,
            "content": self.content,
            "turn_id": self.turn_id,
            "importance": self.importance.value,
            "token_count": self.token_count,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


class ObservationPointer:
    """Utilities for observation pointer format."""

    # Pointer format: [[OBS#<id> tool=<name> tokens=<count> importance=<level>]]
    POINTER_PATTERN = re.compile(
        r"\[\[OBS#(?P<id>[a-f0-9]+)\s+"
        r"tool=(?P<tool>\S+)\s+"
        r"tokens=(?P<tokens>\d+)\s+"
        r"importance=(?P<importance>\w+)\]\]"
    )

    @staticmethod
    def format(observation_id: str, tool_name: str, token_count: int, importance: str) -> str:
        """Generate pointer string for an observation."""
        return f"[[OBS#{observation_id} tool={tool_name} tokens={token_count} importance={importance}]]"

    @classmethod
    def parse(cls, pointer: str) -> dict[str, Any] | None:
        """Parse a pointer string into its components."""
        match = cls.POINTER_PATTERN.search(pointer)
        if match:
            return {
                "observation_id": match.group("id"),
                "tool_name": match.group("tool"),
                "token_count": int(match.group("tokens")),
                "importance": match.group("importance"),
            }
        return None

    @classmethod
    def is_pointer(cls, text: str) -> bool:
        """Check if text contains an observation pointer."""
        return bool(cls.POINTER_PATTERN.search(text))

    @classmethod
    def extract_all(cls, text: str) -> list[dict[str, Any]]:
        """Extract all pointers from text."""
        pointers = []
        for match in cls.POINTER_PATTERN.finditer(text):
            pointers.append(
                {
                    "observation_id": match.group("id"),
                    "tool_name": match.group("tool"),
                    "token_count": int(match.group("tokens")),
                    "importance": match.group("importance"),
                }
            )
        return pointers


class ObservationStore:
    """
    SQLite-backed store for tool observations.

    Provides reversible masking: full content is stored externally,
    and lightweight pointers reference the stored content.
    """

    def __init__(
        self,
        db_path: str | None = None,
        token_counter: Callable | None = None,
    ):
        """
        Initialize the observation store.

        Args:
            db_path: Path to SQLite database. Defaults to .clarity/observations.db
            token_counter: Function to count tokens in text. Defaults to word-based estimate.
        """
        if db_path is None:
            db_path = os.path.join(".clarity", "observations.db")

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.token_counter = token_counter or self._default_token_counter
        self._init_db()

        logger.debug(f"[OBS] ObservationStore initialized: {self.db_path}")

    def _default_token_counter(self, text: str) -> int:
        """Default token counter (word-based estimate ~1.3 tokens/word)."""
        return int(len(text.split()) * 1.3)

    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS observations (
                    observation_id TEXT PRIMARY KEY,
                    tool_name TEXT NOT NULL,
                    args_hash TEXT NOT NULL,
                    content TEXT NOT NULL,
                    turn_id INTEGER NOT NULL,
                    importance TEXT NOT NULL DEFAULT 'normal',
                    token_count INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    metadata TEXT DEFAULT '{}'
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_observations_turn_id
                ON observations(turn_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_observations_tool_name
                ON observations(tool_name)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_observations_importance
                ON observations(importance)
            """)
            conn.commit()

    def _generate_id(self, tool_name: str, args_hash: str, turn_id: int) -> str:
        """Generate unique observation ID."""
        # Use combination of tool, args, turn, and timestamp for uniqueness
        unique_str = f"{tool_name}:{args_hash}:{turn_id}:{time.time()}"
        return hashlib.sha256(unique_str.encode()).hexdigest()[:12]

    def _hash_args(self, args: Any) -> str:
        """Generate hash of tool arguments."""
        if isinstance(args, dict):
            args_str = json.dumps(args, sort_keys=True)
        else:
            args_str = str(args)
        return hashlib.md5(args_str.encode()).hexdigest()[:8]

    def save(
        self,
        tool_name: str,
        args: Any,
        content: str,
        turn_id: int,
        importance: Importance = Importance.NORMAL,
        metadata: dict[str, Any] | None = None,
    ) -> Observation:
        """
        Save a tool observation to the store.

        Args:
            tool_name: Name of the tool that produced this output
            args: Tool arguments (will be hashed)
            content: Full content of the tool output
            turn_id: Current conversation turn ID
            importance: Importance level for masking policy
            metadata: Optional metadata dict

        Returns:
            Observation object with generated ID
        """
        args_hash = self._hash_args(args)
        observation_id = self._generate_id(tool_name, args_hash, turn_id)
        token_count = self.token_counter(content)
        created_at = time.time()
        metadata = metadata or {}

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO observations
                (observation_id, tool_name, args_hash, content, turn_id,
                 importance, token_count, created_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation_id,
                    tool_name,
                    args_hash,
                    content,
                    turn_id,
                    importance.value,
                    token_count,
                    created_at,
                    json.dumps(metadata),
                ),
            )
            conn.commit()

        observation = Observation(
            observation_id=observation_id,
            tool_name=tool_name,
            args_hash=args_hash,
            content=content,
            turn_id=turn_id,
            importance=importance,
            token_count=token_count,
            created_at=created_at,
            metadata=metadata,
        )

        logger.debug(
            f"[OBS] Saved observation #{observation_id} "
            f"tool={tool_name} turn={turn_id} tokens={token_count} "
            f"importance={importance.value}"
        )

        return observation

    def get(self, observation_id: str) -> Observation | None:
        """
        Retrieve an observation by ID.

        Args:
            observation_id: The observation ID to retrieve

        Returns:
            Observation object if found, None otherwise
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM observations WHERE observation_id = ?", (observation_id,)
            )
            row = cursor.fetchone()

        if row is None:
            logger.warning(f"[OBS] Observation #{observation_id} not found")
            return None

        return self._row_to_observation(row)

    def get_content(self, observation_id: str) -> str | None:
        """
        Retrieve just the content for an observation.

        Args:
            observation_id: The observation ID to retrieve

        Returns:
            Content string if found, None otherwise
        """
        observation = self.get(observation_id)
        return observation.content if observation else None

    def rehydrate(self, pointer: str) -> str | None:
        """
        Rehydrate a pointer to its full content.

        Args:
            pointer: Pointer string like [[OBS#abc123 ...]]

        Returns:
            Full content if pointer is valid and observation exists, None otherwise
        """
        parsed = ObservationPointer.parse(pointer)
        if parsed is None:
            logger.warning(f"[OBS] Invalid pointer format: {pointer}")
            return None

        return self.get_content(parsed["observation_id"])

    def find(
        self,
        tool_name: str | None = None,
        turn_id: int | None = None,
        importance: Importance | None = None,
        min_turn_id: int | None = None,
        max_turn_id: int | None = None,
        limit: int = 100,
    ) -> list[Observation]:
        """
        Find observations matching criteria.

        Args:
            tool_name: Filter by tool name
            turn_id: Filter by exact turn ID
            importance: Filter by importance level
            min_turn_id: Filter by minimum turn ID (inclusive)
            max_turn_id: Filter by maximum turn ID (inclusive)
            limit: Maximum number of results

        Returns:
            list of matching Observation objects
        """
        conditions = []
        params = []

        if tool_name is not None:
            conditions.append("tool_name = ?")
            params.append(tool_name)

        if turn_id is not None:
            conditions.append("turn_id = ?")
            params.append(turn_id)

        if importance is not None:
            conditions.append("importance = ?")
            params.append(importance.value)

        if min_turn_id is not None:
            conditions.append("turn_id >= ?")
            params.append(min_turn_id)

        if max_turn_id is not None:
            conditions.append("turn_id <= ?")
            params.append(max_turn_id)

        query = "SELECT * FROM observations"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY turn_id DESC, created_at DESC LIMIT ?"
        params.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

        return [self._row_to_observation(row) for row in rows]

    def find_for_masking(
        self,
        current_turn_id: int,
        mask_age: int = 15,
        exclude_critical: bool = True,
    ) -> list[Observation]:
        """
        Find observations eligible for masking.

        Args:
            current_turn_id: Current conversation turn
            mask_age: Mask observations older than this many turns
            exclude_critical: If True, exclude critical observations

        Returns:
            list of observations eligible for masking
        """
        cutoff_turn = current_turn_id - mask_age

        conditions = ["turn_id <= ?"]
        params = [cutoff_turn]

        if exclude_critical:
            conditions.append("importance != ?")
            params.append(Importance.CRITICAL.value)

        query = f"""
            SELECT * FROM observations
            WHERE {" AND ".join(conditions)}
            ORDER BY importance ASC, turn_id ASC
        """

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

        return [self._row_to_observation(row) for row in rows]

    def _row_to_observation(self, row: sqlite3.Row) -> Observation:
        """Convert database row to Observation object."""
        return Observation(
            observation_id=row["observation_id"],
            tool_name=row["tool_name"],
            args_hash=row["args_hash"],
            content=row["content"],
            turn_id=row["turn_id"],
            importance=Importance(row["importance"]),
            token_count=row["token_count"],
            created_at=row["created_at"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )

    def delete(self, observation_id: str) -> bool:
        """
        Delete an observation by ID.

        Args:
            observation_id: The observation ID to delete

        Returns:
            True if deleted, False if not found
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM observations WHERE observation_id = ?", (observation_id,)
            )
            conn.commit()
            deleted = cursor.rowcount > 0

        if deleted:
            logger.debug(f"[OBS] Deleted observation #{observation_id}")

        return deleted

    def delete_before_turn(self, turn_id: int) -> int:
        """
        Delete all observations before a given turn.

        Args:
            turn_id: Delete observations with turn_id < this value

        Returns:
            Number of observations deleted
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM observations WHERE turn_id < ?", (turn_id,))
            conn.commit()
            deleted = cursor.rowcount

        logger.info(f"[OBS] Deleted {deleted} observations before turn {turn_id}")
        return deleted

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about stored observations."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Total count and tokens
            cursor = conn.execute("""
                SELECT COUNT(*) as count,
                       COALESCE(SUM(token_count), 0) as total_tokens
                FROM observations
            """)
            row = cursor.fetchone()
            total_count = row["count"]
            total_tokens = row["total_tokens"]

            # By importance
            cursor = conn.execute("""
                SELECT importance, COUNT(*) as count, SUM(token_count) as tokens
                FROM observations
                GROUP BY importance
            """)
            by_importance = {
                row["importance"]: {"count": row["count"], "tokens": row["tokens"]}
                for row in cursor.fetchall()
            }

            # By tool
            cursor = conn.execute("""
                SELECT tool_name, COUNT(*) as count, SUM(token_count) as tokens
                FROM observations
                GROUP BY tool_name
                ORDER BY tokens DESC
                LIMIT 10
            """)
            by_tool = {
                row["tool_name"]: {"count": row["count"], "tokens": row["tokens"]}
                for row in cursor.fetchall()
            }

        return {
            "total_count": total_count,
            "total_tokens": total_tokens,
            "by_importance": by_importance,
            "by_tool": by_tool,
        }

    def clear(self) -> int:
        """Clear all observations. Returns count deleted."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM observations")
            conn.commit()
            deleted = cursor.rowcount

        logger.info(f"[OBS] Cleared all {deleted} observations")
        return deleted


# Convenience function for auto-classifying tool importance
def classify_importance(tool_name: str, content: str) -> Importance:
    """
    Auto-classify importance based on tool name and content.

    Rules:
    - CRITICAL: Failing tests, stack traces, errors, diffs
    - LOW: Directory listings, long repetitive logs
    - NORMAL: Everything else
    """
    content_lower = content.lower()

    # Critical indicators
    critical_patterns = [
        "error",
        "exception",
        "traceback",
        "failed",
        "failure",
        "assert",
        "panic",
        "fatal",
        "diff --git",
        "@@",  # diff marker
        "+++ ",
        "--- ",
    ]

    for pattern in critical_patterns:
        if pattern in content_lower:
            return Importance.CRITICAL

    # Low importance indicators
    low_patterns = [
        "directory",
        "total ",
        "drwx",  # ls -l output
        ".pyc",
        "__pycache__",
        "node_modules",
    ]

    # Low importance tools
    low_tools = [
        "list_directory",
        "list_files",
        "ls",
        "find",
    ]

    if tool_name.lower() in low_tools:
        return Importance.LOW

    for pattern in low_patterns:
        if pattern in content_lower:
            return Importance.LOW

    return Importance.NORMAL
