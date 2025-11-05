"""
File Watcher for ClarAIty

Monitors filesystem for changes and emits events for synchronization.
Uses watchdog library with debouncing to avoid excessive events.
"""

import asyncio
import logging
from pathlib import Path
from typing import Set, List, Optional, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from .event_bus import event_bus, emit_file_changed, EventType, ClarityEvent

logger = logging.getLogger(__name__)


@dataclass
class FileChange:
    """Represents a file change event."""
    file_path: str
    change_type: str  # created, modified, deleted
    timestamp: datetime


class ClarityFileEventHandler(FileSystemEventHandler):
    """
    Custom event handler for ClarAIty file watcher.

    Filters relevant files and debounces rapid changes.
    """

    def __init__(
        self,
        watch_patterns: List[str],
        ignore_patterns: List[str],
        debounce_callback: Callable[[Set[FileChange]], None]
    ):
        """
        Initialize event handler.

        Args:
            watch_patterns: File patterns to watch (e.g., ["*.py", "*.md"])
            ignore_patterns: Patterns to ignore (e.g., ["__pycache__", ".git"])
            debounce_callback: Callback for debounced changes
        """
        super().__init__()
        self.watch_patterns = watch_patterns
        self.ignore_patterns = ignore_patterns
        self.debounce_callback = debounce_callback
        self.pending_changes: Set[FileChange] = set()
        self.debounce_timer: Optional[asyncio.Task] = None
        self.debounce_delay = 2.0  # seconds

    def should_process(self, file_path: str) -> bool:
        """
        Determine if file should be processed.

        Args:
            file_path: Path to file

        Returns:
            True if file should be watched
        """
        path = Path(file_path)

        # Check ignore patterns
        for pattern in self.ignore_patterns:
            if pattern in str(path):
                return False

        # Check watch patterns (if specified)
        if self.watch_patterns:
            for pattern in self.watch_patterns:
                if path.match(pattern):
                    return True
            return False

        return True

    def on_created(self, event: FileSystemEvent):
        """Handle file creation."""
        if not event.is_directory and self.should_process(event.src_path):
            logger.debug(f"File created: {event.src_path}")
            self._add_change(event.src_path, "created")

    def on_modified(self, event: FileSystemEvent):
        """Handle file modification."""
        if not event.is_directory and self.should_process(event.src_path):
            logger.debug(f"File modified: {event.src_path}")
            self._add_change(event.src_path, "modified")

    def on_deleted(self, event: FileSystemEvent):
        """Handle file deletion."""
        if not event.is_directory and self.should_process(event.src_path):
            logger.debug(f"File deleted: {event.src_path}")
            self._add_change(event.src_path, "deleted")

    def _add_change(self, file_path: str, change_type: str):
        """
        Add a file change to pending queue with debouncing.

        Args:
            file_path: Path to changed file
            change_type: Type of change (created, modified, deleted)
        """
        # Normalize path
        file_path = str(Path(file_path).resolve())

        # Add to pending changes (set automatically deduplicates)
        change = FileChange(
            file_path=file_path,
            change_type=change_type,
            timestamp=datetime.utcnow()
        )

        # Remove any previous change for same file (keep latest)
        self.pending_changes = {c for c in self.pending_changes if c.file_path != file_path}
        self.pending_changes.add(change)

        # Reset debounce timer
        if self.debounce_timer:
            self.debounce_timer.cancel()

        # Schedule debounced callback
        try:
            loop = asyncio.get_event_loop()
            self.debounce_timer = loop.call_later(
                self.debounce_delay,
                self._flush_changes
            )
        except RuntimeError:
            # No event loop - process immediately
            self._flush_changes()

    def _flush_changes(self):
        """Flush pending changes to callback."""
        if self.pending_changes:
            changes = self.pending_changes.copy()
            self.pending_changes.clear()
            logger.info(f"Flushing {len(changes)} file changes after debounce")
            self.debounce_callback(changes)


class FileWatcher:
    """
    Monitor filesystem for changes and emit sync events.

    Features:
    - Watchdog-based monitoring
    - Debouncing (2-second window to batch rapid changes)
    - Pattern filtering (watch only relevant files)
    - Event emission via EventBus
    """

    def __init__(
        self,
        watch_directory: str,
        watch_patterns: Optional[List[str]] = None,
        ignore_patterns: Optional[List[str]] = None
    ):
        """
        Initialize file watcher.

        Args:
            watch_directory: Directory to watch
            watch_patterns: File patterns to watch (default: *.py)
            ignore_patterns: Patterns to ignore (default: common temp/cache dirs)
        """
        self.watch_directory = Path(watch_directory).resolve()

        # Default patterns
        self.watch_patterns = watch_patterns or ["*.py", "*.md", "*.txt", "*.json"]
        self.ignore_patterns = ignore_patterns or [
            "__pycache__",
            ".git",
            ".venv",
            "venv",
            "node_modules",
            ".pytest_cache",
            ".mypy_cache",
            "*.pyc",
            "*.pyo",
            ".DS_Store",
            ".clarity",  # Don't watch ClarAIty's own database
        ]

        self.observer: Optional[Observer] = None
        self.event_handler: Optional[ClarityFileEventHandler] = None
        self._running = False

        logger.info(
            f"FileWatcher initialized for {self.watch_directory} "
            f"(patterns: {self.watch_patterns})"
        )

    def start(self):
        """Start watching filesystem."""
        if self._running:
            logger.warning("FileWatcher already running")
            return

        logger.info(f"Starting FileWatcher on {self.watch_directory}")

        # Create event handler
        self.event_handler = ClarityFileEventHandler(
            watch_patterns=self.watch_patterns,
            ignore_patterns=self.ignore_patterns,
            debounce_callback=self._on_changes_debounced
        )

        # Create and start observer
        self.observer = Observer()
        self.observer.schedule(
            self.event_handler,
            str(self.watch_directory),
            recursive=True
        )
        self.observer.start()

        self._running = True
        logger.info("FileWatcher started successfully")

    def stop(self):
        """Stop watching filesystem."""
        if not self._running:
            return

        logger.info("Stopping FileWatcher")

        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=5)

        self._running = False
        logger.info("FileWatcher stopped")

    def is_running(self) -> bool:
        """Check if watcher is running."""
        return self._running

    def _on_changes_debounced(self, changes: Set[FileChange]):
        """
        Handle debounced file changes.

        Args:
            changes: Set of file changes
        """
        if not changes:
            return

        logger.info(f"Processing {len(changes)} debounced file changes")

        # Emit batch event
        try:
            loop = asyncio.get_event_loop()
            asyncio.create_task(self._emit_batch_event(changes))
        except RuntimeError:
            # No event loop - skip event emission
            logger.warning("No event loop available, skipping event emission")

    async def _emit_batch_event(self, changes: Set[FileChange]):
        """
        Emit batch file changes event.

        Args:
            changes: Set of file changes
        """
        # Group by change type
        created = [c.file_path for c in changes if c.change_type == "created"]
        modified = [c.file_path for c in changes if c.change_type == "modified"]
        deleted = [c.file_path for c in changes if c.change_type == "deleted"]

        await event_bus.publish(ClarityEvent(
            type=EventType.FILES_BATCH_CHANGED,
            source="file_watcher",
            data={
                'created': created,
                'modified': modified,
                'deleted': deleted,
                'total_count': len(changes),
            }
        ))

        logger.info(
            f"Emitted batch event: {len(created)} created, "
            f"{len(modified)} modified, {len(deleted)} deleted"
        )


# Global file watcher instance (created on demand)
_global_watcher: Optional[FileWatcher] = None


def get_global_watcher(
    watch_directory: Optional[str] = None,
    watch_patterns: Optional[List[str]] = None,
    ignore_patterns: Optional[List[str]] = None
) -> FileWatcher:
    """
    Get or create global file watcher instance.

    Args:
        watch_directory: Directory to watch (required on first call)
        watch_patterns: File patterns to watch
        ignore_patterns: Patterns to ignore

    Returns:
        Global FileWatcher instance
    """
    global _global_watcher

    if _global_watcher is None:
        if watch_directory is None:
            raise ValueError("watch_directory required on first call")
        _global_watcher = FileWatcher(watch_directory, watch_patterns, ignore_patterns)

    return _global_watcher


def start_watching(
    watch_directory: str,
    watch_patterns: Optional[List[str]] = None,
    ignore_patterns: Optional[List[str]] = None
):
    """
    Start global file watcher.

    Args:
        watch_directory: Directory to watch
        watch_patterns: File patterns to watch
        ignore_patterns: Patterns to ignore
    """
    watcher = get_global_watcher(watch_directory, watch_patterns, ignore_patterns)
    watcher.start()


def stop_watching():
    """Stop global file watcher."""
    global _global_watcher
    if _global_watcher:
        _global_watcher.stop()
        _global_watcher = None
