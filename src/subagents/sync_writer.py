"""Synchronous JSONL writer for subagent transcript persistence.

Unlike SessionWriter (async, thread-safe), this is a simple synchronous
writer for use in subagent execution which runs synchronously.
"""

import json
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from src.observability import get_logger

if TYPE_CHECKING:
    from src.session.store.memory_store import StoreNotification

logger = get_logger("subagents.sync_writer")


class SyncJSONLWriter:
    """Synchronous JSONL writer for subagent transcripts.

    Writes one JSON object per line. Auto-flushes after each write
    for crash safety.
    """

    def __init__(self, file_path: Path):
        self._file_path = Path(file_path)
        self._file = None

    def open(self) -> None:
        """Open the file for appending. Creates parent directories if needed."""
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self._file_path, "a", encoding="utf-8")
        logger.info(f"SyncJSONLWriter opened: {self._file_path}")

    def close(self) -> None:
        """Flush and close the file."""
        if self._file:
            self._file.flush()
            self._file.close()
            self._file = None

    def write(self, data: dict) -> None:
        """Write a single JSON object as one line."""
        if not self._file:
            return
        line = json.dumps(data, default=str, ensure_ascii=False)
        self._file.write(line + "\n")
        self._file.flush()

    def write_notification(self, notification: "StoreNotification") -> None:
        """Write a store notification to the transcript."""
        if not self._file:
            return
        try:
            record = {
                "event": notification.event.value if hasattr(notification.event, 'value') else str(notification.event),
            }
            if notification.message:
                msg = notification.message
                record["role"] = msg.role
                record["content"] = msg.content
                if hasattr(msg, 'meta') and msg.meta:
                    record["meta"] = {
                        k: v for k, v in vars(msg.meta).items()
                        if v is not None
                    }
            self.write(record)
        except Exception as e:
            logger.error(f"Failed to write notification: {e}")
