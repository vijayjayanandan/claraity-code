"""Thread-safe async JSONL writer with drain-on-close.

Features:
- Thread-safe via run_coroutine_threadsafe() with captured loop
- Drain pending writes on close (v3.1 Patch 3)
- Auto-flush after each event (process-crash safe)
- Binds to MessageStore for reactive persistence

Durability Guarantee:
- After flush() returns, data survives PROCESS CRASH
- NOT guaranteed: power-loss durability (no os.fsync)
"""

import json
import asyncio
import threading
from pathlib import Path
from typing import Union, Optional, Callable, TYPE_CHECKING
from dataclasses import dataclass

from src.observability import get_logger

if TYPE_CHECKING:
    from ..models.message import Message, FileHistorySnapshot
    from ..store.memory_store import MessageStore, StoreNotification

logger = get_logger("session.persistence.writer")


@dataclass
class WriteResult:
    """Result of a write operation."""
    success: bool
    bytes_written: int = 0
    error: Optional[str] = None


class SessionWriter:
    """
    Thread-safe async JSONL session writer with drain-on-close.

    Thread Safety:
    - Captures event loop at open() time
    - Uses run_coroutine_threadsafe() for cross-thread scheduling
    - Tracks pending writes and drains on close (v3.1 Patch 3)

    Durability Guarantee:
    - After flush() returns, data survives PROCESS CRASH
    - NOT guaranteed: power-loss durability (no os.fsync)
    """

    def __init__(
        self,
        file_path: Union[str, Path],
        on_error: Optional[Callable[[Exception], None]] = None,
        drain_timeout: float = 5.0
    ):
        self._file_path = Path(file_path)
        self._on_error = on_error
        self._drain_timeout = drain_timeout

        # Async state
        self._file = None
        self._write_lock: Optional[asyncio.Lock] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Pending write tracking (thread-safe) - v3.1 Patch 3
        self._pending_count: int = 0
        self._pending_lock = threading.Lock()
        self._drain_complete: Optional[asyncio.Event] = None

        # Stats
        self._total_writes = 0
        self._total_bytes = 0

        # Store subscription
        self._unsubscribe: Optional[Callable] = None

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def open(self) -> None:
        """
        Open the file for writing.

        MUST be called from the async context where events will be processed.
        """
        self._loop = asyncio.get_running_loop()
        self._write_lock = asyncio.Lock()
        self._drain_complete = asyncio.Event()
        self._drain_complete.set()  # Initially "drained" (nothing pending)

        # Ensure parent directory exists
        self._file_path.parent.mkdir(parents=True, exist_ok=True)

        # Use regular file I/O (aiofiles optional, sync is fine for appends)
        self._file = open(self._file_path, 'a', encoding='utf-8')
        logger.info(f"SessionWriter opened: {self._file_path}")

    async def close(self) -> None:
        """
        Close the file gracefully, draining pending writes first.

        Waits up to drain_timeout seconds for pending writes to complete.
        """
        # Unbind first to stop new events
        self.unbind()

        # Wait for pending writes to drain (v3.1 Patch 3)
        if self._pending_count > 0:
            logger.info(f"Draining {self._pending_count} pending writes...")
            try:
                await asyncio.wait_for(
                    self._drain_complete.wait(),
                    timeout=self._drain_timeout
                )
                logger.info("Writer drain complete")
            except asyncio.TimeoutError:
                logger.warning(
                    f"Writer drain timeout after {self._drain_timeout}s, "
                    f"{self._pending_count} writes may be lost"
                )

        # Now safe to close
        if self._file:
            await self.flush()
            self._file.close()
            self._file = None
            logger.info(f"SessionWriter closed: {self._file_path}")

        self._loop = None

    def bind_to_store(self, store: "MessageStore") -> None:
        """
        Bind writer to a message store.

        Thread-safe: events from any thread are scheduled to the writer's loop.
        """
        if self._loop is None:
            raise RuntimeError("Writer must be opened before binding to store")

        from ..store.memory_store import StoreEvent, StoreNotification

        def sync_handler(notification: "StoreNotification") -> None:
            """Thread-safe sync wrapper with pending tracking."""
            if self._loop is None or not self._loop.is_running():
                logger.error("Writer not running, dropping event")
                return

            # Atomically increment pending count and schedule event clear
            # Note: We always schedule clear() - it's idempotent and avoids
            # race conditions from checking is_set() from another thread
            should_clear = False
            with self._pending_lock:
                self._pending_count += 1
                should_clear = self._pending_count == 1  # First pending write

            # Schedule event manipulation from event loop thread (thread-safe)
            if should_clear and self._drain_complete:
                self._loop.call_soon_threadsafe(self._drain_complete.clear)

            # Schedule the async handler
            future = asyncio.run_coroutine_threadsafe(
                self._handle_event_tracked(notification),
                self._loop
            )

            # Add error callback for visibility
            def on_done(f):
                try:
                    f.result()  # Raises if coroutine raised
                except Exception as e:
                    logger.error(f"Write handler error: {e}")
                    if self._on_error:
                        self._on_error(e)

            future.add_done_callback(on_done)

        self._unsubscribe = store.subscribe(sync_handler)
        logger.debug("Writer bound to store")

    async def _handle_event_tracked(self, notification: "StoreNotification") -> None:
        """Handle event and decrement pending count when done.

        Persists all message events to the JSONL ledger:
        - MESSAGE_ADDED: New message (first appearance)
        - MESSAGE_UPDATED: Streaming update (collapse by stream_id)
        - MESSAGE_FINALIZED: Stream complete marker

        The ledger keeps full history; the store projection collapses.
        """
        from ..store.memory_store import StoreEvent

        try:
            if notification.event == StoreEvent.MESSAGE_ADDED:
                await self.write_message(notification.message)
                await self.flush()
            elif notification.event == StoreEvent.MESSAGE_UPDATED:
                # Skip streaming updates to reduce JSONL bloat
                # Only MESSAGE_ADDED and MESSAGE_FINALIZED are persisted
                # Trade-off: If crash mid-stream, partial content is lost
                pass
            elif notification.event == StoreEvent.MESSAGE_FINALIZED:
                # Finalization marker - write final state with stop_reason
                await self.write_message(notification.message)
                await self.flush()
            elif notification.event == StoreEvent.SNAPSHOT_ADDED:
                await self.write_snapshot(notification.snapshot)
                await self.flush()
        finally:
            # Atomically decrement pending count and check if drained
            should_signal = False
            with self._pending_lock:
                self._pending_count -= 1
                should_signal = self._pending_count == 0  # All writes complete

            # Signal drain complete (we're already on the event loop thread)
            if should_signal and self._drain_complete:
                self._drain_complete.set()

    def unbind(self) -> None:
        """Unbind from store."""
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

    # =========================================================================
    # Write Operations
    # =========================================================================

    async def write_message(self, message: "Message") -> WriteResult:
        """Write a message to the JSONL file."""
        return await self._write_line(message.to_dict())

    async def write_snapshot(self, snapshot: "FileHistorySnapshot") -> WriteResult:
        """Write a file snapshot to the JSONL file."""
        return await self._write_line(snapshot.to_dict())

    async def write_raw(self, data: dict) -> WriteResult:
        """Write raw dict to the JSONL file."""
        return await self._write_line(data)

    async def write_agent_state(
        self,
        session_id: str,
        todos: list,
        current_todo_id: Optional[str] = None,
        last_stop_reason: Optional[str] = None,
        seq: Optional[int] = None
    ) -> WriteResult:
        """
        Write agent state to the JSONL file as a system event.

        Creates a system message with:
        - role="system"
        - meta.event_type="agent_state"
        - meta.include_in_llm_context=False
        - meta.extra={ todos, current_todo_id, last_stop_reason }

        This is used for session resume to restore agent runtime state.

        Args:
            session_id: Current session ID
            todos: List of todo dicts
            current_todo_id: ID of currently active todo
            last_stop_reason: Last stop reason for context
            seq: Optional sequence number (auto-generated if not provided)

        Returns:
            WriteResult indicating success/failure
        """
        from ..models.message import Message

        message = Message.create_agent_state(
            session_id=session_id,
            todos=todos,
            current_todo_id=current_todo_id,
            last_stop_reason=last_stop_reason,
            seq=seq or 0
        )

        result = await self.write_message(message)
        await self.flush()
        return result

    async def _write_line(self, data: dict) -> WriteResult:
        """Write a single JSON line."""
        if not self._file:
            return WriteResult(success=False, error="File not open")

        try:
            async with self._write_lock:
                line = json.dumps(data, ensure_ascii=False)
                self._file.write(line + '\n')

                self._total_writes += 1
                self._total_bytes += len(line) + 1

                return WriteResult(success=True, bytes_written=len(line) + 1)

        except Exception as e:
            logger.error(f"Write error: {e}")
            if self._on_error:
                self._on_error(e)
            return WriteResult(success=False, error=str(e))

    async def flush(self) -> None:
        """
        Flush all buffered writes to OS.

        Guarantee: After this returns, data survives PROCESS CRASH.
        """
        if self._file:
            async with self._write_lock:
                self._file.flush()

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def file_path(self) -> Path:
        return self._file_path

    @property
    def total_writes(self) -> int:
        return self._total_writes

    @property
    def total_bytes(self) -> int:
        return self._total_bytes

    @property
    def is_open(self) -> bool:
        return self._file is not None

    @property
    def pending_writes(self) -> int:
        with self._pending_lock:
            return self._pending_count


# =========================================================================
# Convenience Functions
# =========================================================================

def create_session_file(file_path: Union[str, Path]) -> Path:
    """Create a new empty session file."""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


async def append_to_session(
    file_path: Union[str, Path],
    message: Union["Message", "FileHistorySnapshot", dict]
) -> WriteResult:
    """
    Async append a single message to session file.
    Opens, writes, flushes, closes.

    Use for one-off writes. For streaming, use SessionWriter.
    """
    try:
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(message, dict):
            line = json.dumps(message, ensure_ascii=False)
        else:
            line = json.dumps(message.to_dict(), ensure_ascii=False)

        with open(path, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
            f.flush()

        return WriteResult(success=True, bytes_written=len(line) + 1)

    except Exception as e:
        return WriteResult(success=False, error=str(e))
